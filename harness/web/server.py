"""Lesson 53: the web server. The same Session as the terminal, driven over HTTP.

Python's own http.server, one thread per request (ADR 0051). The page talks to it in two directions:

    browser ── POST /api/send {"text"} ──▶ a worker thread runs the request (or a slash command)
    browser ◀── GET /events (Server-Sent Events) ── every event the session reports, numbered

- GET  /              the page; the first visit swaps the key in the address for a cookie
- GET  /static/NAME   its script and style
- GET  /api/state     the conversation so far, the status line's facts, and the last event's number
- GET  /events        the live stream from that number on (a reconnecting page says where it got to)
- POST /api/send      a request or a slash command; 409 while one is running
- POST /api/stop      stop the running request, as Esc does in the terminal
- GET  /api/files     a folder of the workspace, for the explorer (Lesson 54)
- GET  /api/file      a text file of the workspace, for the viewer, with secrets hidden
- POST /api/answer    {"id", "answer"}: answer the question the agent is waiting on: an approval, a choice, text (Lesson 55)
- GET  /api/chats     this project's saved chats and the projects used before; GET /api/journal, GET /api/settings (Lesson 56)
- POST /api/project   {"path"}: open a project used before; POST /api/connect {"provider", "model", "base_url"}: another model

Only this computer can connect (127.0.0.1), the Host header must name it, and every request needs the key.
"""
import json
import os
import re
import secrets
import socket
import threading
import webbrowser
from contextlib import nullcontext
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx

from harness import config
from harness.chats import ChatStore
from harness.cli import announce, handle_line
from harness.commands import load_commands, resume_text
from harness.config import ConfigError, describe, load_dotenv, load_settings
from harness.providers.base import ProviderError
from harness.providers.factory import OPENAI_COMPATIBLE, PROVIDERS
from harness.security.permissions import CHANGES
from harness.security.redact import redacted
from harness.session import Session
from harness.styles import load_styles
from harness.tui.latex import render_math
from harness.tui.plain import always_label
from harness.web import DEFAULT_PORT
from harness.workspace import IGNORED_DIRS, Workspace

STATIC = Path(__file__).parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml"}            # fixed: Windows' registry can map .js to text/plain, and browsers refuse to run that
KEEP = 5000                  # events kept for a page that reconnects; more than that and it reloads the state instead
PING = 15                    # seconds between keep-alive comments on a quiet stream (also how a closed tab is noticed)
RESULT_CHARS = 4000          # of a tool result, sent to the page
MAX_BODY = 1_000_000
FILE_BYTES = 200_000         # of a file shown in the viewer
FOLDER_ENTRIES = 500         # of a folder shown in the explorer
PREVIEW_CHARS = 20_000       # of a diff shown with an approval question
ANSWER_CHARS = 4_000         # of an answer typed in the page
NOT_RUN = ("tool_denied", "tool_refused")


class Hub:
    """Everything the session said, for every open page: numbered, the newest KEEP kept, so a page that reconnects gets what it missed."""

    def __init__(self, keep: int = KEEP):
        self.keep, self.events, self.last = keep, [], 0
        self.changed = threading.Condition()

    def publish(self, event: dict) -> None:
        data = json.dumps(event, ensure_ascii=False, default=str)       # one line: JSON escapes newlines
        with self.changed:
            self.last += 1
            self.events.append((self.last, data))
            del self.events[:-self.keep]
            self.changed.notify_all()

    def after(self, last: int, timeout: float) -> list[tuple[int, str]]:
        """Events numbered after `last`, waiting up to `timeout` seconds for one."""
        with self.changed:
            if last > self.last:                 # from a page that saw another server: start again
                last = 0
            self.changed.wait_for(lambda: self.last > last, timeout)
            return [(i, e) for i, e in self.events if i > last]


def call_json(call) -> dict:
    return {"id": call.id, "name": call.name, "args": call.arguments}


def result_json(call_id: str, name: str, text: str) -> dict:
    return {"type": "tool_result", "id": call_id, "name": name, "text": text[:RESULT_CHARS], "chars": len(text),
            "error": text.startswith("Error")}


NOTES = {                    # events the page shows as one line
    "compacting": lambda n: f"the window is nearly full: summarising {n} older messages",
    "compact": lambda c: f"summarised {c.removed} messages (~{c.before:,} -> ~{c.after:,} tokens)",
    "compact_failed": lambda why: f"couldn't summarise: {why}",
    "microcompact": lambda m: f"cleared {len(m.cleared)} old tool results (~{m.saved:,} tokens)",
    "nudge": lambda _: "the todo list still has open items: asking the agent to carry on",
    "notice": lambda text: text,
    "limit": lambda why: f"stopped: {why}",
    "redacted": lambda d: f"hid {', '.join(d[1])} in the result of {d[0].name}",
}


def event_json(kind: str, data) -> dict | None:
    """An agent event as JSON for the page, or None for one the page doesn't need (docs/reference/events.md)."""
    if kind in ("text_delta", "thinking_delta"):
        return {"type": kind, "text": data}
    if kind == "tool_call":
        return {"type": kind} | call_json(data)
    if kind == "tool_result":
        return result_json(data[0].id, data[0].name, data[1])
    if kind in NOT_RUN:
        call, reason = (data, "you said no") if kind == "tool_denied" else data
        return {"type": kind, "id": call.id, "reason": reason}
    if kind == "model_call":
        return {"type": kind}
    if kind == "model_reply":
        return {"type": kind, "input_tokens": data.usage.input_tokens, "output_tokens": data.usage.output_tokens}
    if kind == "context":
        return {"type": kind, "tokens": data.estimated, "window": data.window, "level": data.level}
    if kind == "todos":
        return {"type": kind, "items": data}
    if kind == "task":
        return {"type": kind, "id": data[1].id, "command": data[1].command, "text": data[1].describe()}
    if kind == "subagent":
        name, what, info = data
        return {"type": kind, "name": name, "what": what, "info": call_json(info) if what == "tool_call" else info}
    if kind == "rolled_back":
        return {"type": kind}
    if kind in NOTES:
        return {"type": "note", "text": NOTES[kind](data)}
    return None


FENCED = re.compile(r'<untrusted source="[^"]*">\n(.*?)\n</untrusted>', re.DOTALL)


def unfenced(content: str) -> str:
    """A result as the tool returned it: the model read it fenced (Lesson 31), the page shows the text, as it does live."""
    found = FENCED.match(content)
    return found.group(1) + content[found.end():] if found else content


def transcript(messages) -> list[dict]:
    """The conversation so far, as the same events the page gets live, so one renderer draws both."""
    out = []
    for m in messages[1:]:                      # not the system prompt
        if m.role == "user":
            out.append({"type": "user", "text": m.content})
        elif m.role == "assistant":
            if m.content:
                out.append({"type": "answer", "text": m.content, "markdown": render_math(m.content)})
            out += [{"type": "tool_call"} | call_json(c) for c in m.tool_calls]
        elif m.role == "tool":
            out.append(result_json(m.tool_call_id, m.tool_name, unfenced(m.content)))
    return out


def folder_json(ws: Workspace, path: str) -> dict:
    """One folder for the explorer: what the agent's list_dir would see (the jail, without the folders it skips)."""
    folder = ws.path(path or ".")
    if not folder.is_dir():
        raise FileNotFoundError(f"'{path}' is not a folder")
    entries = []
    for p in sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[:FOLDER_ENTRIES]:
        if not (p.is_dir() and p.name in IGNORED_DIRS) and not ws.leads_outside(p):
            entries.append({"name": p.name, "path": ws.display(p), "dir": p.is_dir()})
    return {"path": ws.display(folder), "entries": entries}


def file_json(ws: Workspace, path: str) -> dict:
    """A text file for the viewer: through the jail, the start of a big one, secrets hidden (the page may be on a shared screen)."""
    p = ws.path(path)
    if not p.is_file():
        raise FileNotFoundError(f"'{path}' is not a file")
    with p.open("rb") as f:
        data = f.read(FILE_BYTES + 1)
    if b"\0" in data[:8000]:
        return {"path": ws.display(p), "binary": True}
    return {"path": ws.display(p), "text": redacted(data[:FILE_BYTES].decode("utf-8", "replace")), "truncated": len(data) > FILE_BYTES}


class Question:
    """What the agent waits for (Lesson 55): shown in every open page, answered by the first one that answers."""

    def __init__(self, payload: dict, default):
        self.payload, self.default, self.answer = payload, default, default
        self.done = threading.Event()


def check_answer(payload: dict, answer) -> str | None:
    """Why `answer` can't answer this question, or None. The page is trusted no more than its form fields."""
    kind = payload["kind"]
    if kind == "approval":
        allowed = {"yes", "no"} | ({"always"} if payload["always"] else set())
        return None if answer in allowed else f"answer one of: {', '.join(sorted(allowed))}"
    if kind == "choice":
        return None if answer == "" or answer in payload["options"] else "answer one of the options"
    return None if isinstance(answer, str) and len(answer) <= ANSWER_CHARS else f"answer with text of at most {ANSWER_CHARS:,} characters"


class WebUI:
    """The Session's ui in the browser: every event and message becomes an event in the hub, and a question waits for a page."""

    def __init__(self, hub: Hub):
        self.hub = hub
        self.stop = threading.Event()      # /api/stop: the next event in the turn's thread raises KeyboardInterrupt
        self.turn: threading.Thread | None = None
        self.question: Question | None = None
        self.asked = 0
        self.lock = threading.Lock()

    # --- questions (Lesson 55): the agent's thread waits; a page's POST /api/answer, or Stop, wakes it -------------------------
    def ask(self, payload: dict, default):
        with self.lock:
            self.asked += 1
            question = self.question = Question(payload | {"type": "question", "id": f"q{self.asked}"}, default)
        self.hub.publish(question.payload)
        if self.stop.is_set():                   # Stop came first: don't wait for an answer nobody will give
            self.cancel()
        question.done.wait()
        with self.lock:
            self.question = None
        shown = question.answer if payload["kind"] != "text" else bool(question.answer)    # typed text isn't repeated to every page
        self.hub.publish({"type": "answered", "id": question.payload["id"], "answer": shown})
        return question.answer

    def reply(self, qid, answer) -> str | None:
        """A page's answer: None when it was taken, else why not."""
        with self.lock:
            question = self.question
            if question is None or question.payload["id"] != qid or question.done.is_set():
                return "that question isn't waiting (answered already, or stopped)"
            why = check_answer(question.payload, answer)
            if why is None:
                question.answer = answer
                question.done.set()
            return why

    def cancel(self) -> None:
        """Stop: the waiting question gets its safe answer (no, or nothing)."""
        with self.lock:
            if self.question is not None and not self.question.done.is_set():
                self.question.answer = self.question.default
                self.question.done.set()

    def ask_choice(self, question: str, options: dict[str, str]) -> str:
        return self.ask({"kind": "choice", "question": question, "options": options}, "")

    def ask_text(self, question: str) -> str:
        return self.ask({"kind": "text", "question": question}, "")

    def show_plan(self, plan: str) -> None:
        self.hub.publish({"type": "plan", "text": plan, "markdown": render_math(plan)})

    def __call__(self, kind, data):
        if self.stop.is_set() and threading.current_thread() is self.turn:
            self.stop.clear()
            raise KeyboardInterrupt        # the agent's own cancel path rolls the turn back, as Esc does in the terminal
        event = event_json(kind, data)
        if event is not None:
            self.hub.publish(event)

    def say(self, kind: str, text: str) -> None:
        self.hub.publish({"type": kind, "text": text})

    def info(self, text):
        self.say("info", text)

    def warn(self, text):
        self.say("warn", text)

    def error(self, text):
        self.say("error", text)

    def usage_line(self, text):
        self.say("usage", text)

    def banner(self, title, details):
        self.say("info", f"{title} · {details}")

    def answer(self, text):
        self.hub.publish({"type": "answer", "text": text, "markdown": render_math(text)})

    def retry(self, notice):
        self.warn(f"{notice.error}: " + ("switching to the fallback model" if notice.fallback else
                                         f"retrying in {notice.delay:.1f} s (retry {notice.attempt})"))


class WebApprover:
    """Asks the page about a call the permissions sent to "ask" (Lesson 55): the terminal's question, with the diff, the command, the
    reason and the risks. yes, no, or always (when the permissions offer a rule to remember)."""

    def __init__(self, ui: WebUI):
        self.ui = ui

    def __call__(self, call, tool, decision=None) -> bool | str:
        try:
            preview = tool.preview(**call.arguments) if tool.preview else ""
        except Exception as e:                      # a preview that fails mustn't stop the question
            preview = f"(no preview: {e})"
        answer = self.ui.ask({"kind": "approval", "call_id": call.id, "tool": tool.name, "args": call.arguments,
                              "preview": preview[:PREVIEW_CHARS], "destructive": tool.is_destructive(call.arguments),
                              "reason": decision.reason if decision and decision.reason != CHANGES else "",
                              "notes": list(decision.notes) if decision else [], "always": always_label(decision)}, "no")
        return {"yes": True, "always": "always"}.get(answer, False)


def build_session(workspace: Path, flags: dict, ui: WebUI, fresh: bool = False) -> tuple[Session, object]:
    """What `harness` does at start, for one project and the command line's settings, with the page as the interface (Lesson 56:
    also when the page opens another project or connects another model)."""
    load_dotenv(workspace)                                       # never overrides a variable that is already set
    settings, warnings = load_settings(workspace, flags)        # ConfigError: the caller keeps what it had
    ws = Workspace(workspace, extra_dirs=[workspace / Path(d).expanduser() for d in settings.additional_directories])
    commands = load_commands(workspace)
    styles, style_warnings = load_styles(workspace)
    for warning in warnings + commands.warnings + style_warnings:
        ui.warn(f"warning: {warning}")
    session = Session(settings, ws, ui, WebApprover(ui), styles, interface="web", fresh=fresh)
    session.commands = commands
    ui.banner("Agent harness", f"{settings.provider} · {session.provider.model} · {ws.root}")
    announce(session)
    return session, commands


def ollama_models(base_url: str | None) -> list[str]:
    """The models the Ollama server has, for the settings' list; [] when it doesn't answer."""
    try:
        r = httpx.get(f"{(base_url or 'http://localhost:11434').rstrip('/')}/api/tags", timeout=2)
        return sorted(m["name"] for m in r.json().get("models", []))
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return []


def key_variable(provider: str) -> str | None:
    return "ANTHROPIC_API_KEY" if provider == "anthropic" else OPENAI_COMPATIBLE.get(provider, (None, None))[1]


class WebApp:
    """What the server runs: one session, the hub its events go to, and the request in progress."""

    def __init__(self, session: Session, commands, flags: dict | None = None):
        self.session, self.commands, self.ui = session, commands, session.ui
        self.flags = dict(flags or {})           # the command line's settings: kept when the page opens another project or model (Lesson 56)
        self.lock = threading.Lock()
        self.keys = SimpleNamespace(watching=nullcontext)      # run_turn's keyboard watcher: the browser has a Stop button instead
        self.notes: list[dict] = []          # what was said before any page was open (the banner, warnings): shown first on every page

    @property
    def busy(self) -> bool:
        return self.ui.turn is not None and self.ui.turn.is_alive()

    def send(self, text: str, action=None) -> bool:
        """Start a request, a command, or `action` (Lesson 56) on a worker thread. False while one is running."""
        with self.lock:
            if self.busy:
                return False
            self.ui.stop.clear()
            self.ui.turn = threading.Thread(target=self.run, args=(text, action), name="harness-turn", daemon=True)
            self.ui.turn.start()
            return True

    def shape(self) -> tuple:
        """Which conversation this is: another session, another list (/reset, /resume), or a shorter one (/rewind, /compact) means redraw."""
        return id(self.session), id(self.session.agent.messages), len(self.session.agent.messages)

    def run(self, text: str, action=None) -> None:
        hub = self.ui.hub
        if action is None:
            hub.publish({"type": "user", "text": text})
        else:
            self.ui.info(text)
        hub.publish({"type": "busy", "busy": True})
        before = self.shape()
        try:
            if action is not None:
                action()
            else:
                self.session.announce_tasks()          # background tasks that ended since the last request (Lesson 48)
                if not handle_line(self.session, self.keys, self.commands, text):
                    self.ui.info("/bye ends a terminal session; here, close the tab (Ctrl+C in the server's terminal stops the server)")
        except KeyboardInterrupt:
            self.ui.error("stopped")
        except (ConfigError, ProviderError) as e:
            self.ui.error(str(e))
        except Exception as e:                     # a bug in one request mustn't take the server down
            self.ui.error(f"{type(e).__name__}: {e}")
        finally:
            self.ui.stop.clear()
            after = self.shape()
            if after[:2] != before[:2] or after[2] < before[2]:
                hub.publish({"type": "conversation"})       # the pages draw it again from /api/state
            hub.publish({"type": "busy", "busy": False, "status": self.session.status() | {"busy": False}})   # this thread is still alive

    # --- projects, models and chats (Lesson 56) -------------------------------------------------------------------------------
    def replace(self, workspace: Path, overrides: dict, resume: str | None = None) -> None:
        """A new session for `workspace` with these settings; the old one closes only once the new one works."""
        first = self.ui.hub.last
        session, commands = build_session(workspace, self.flags | overrides, self.ui, self.session.fresh)
        self.session.close()
        self.session, self.commands = session, commands
        self.flags |= overrides
        self.notes = [e for i, data in self.ui.hub.events if i > first and (e := json.loads(data))["type"] in ("info", "warn")]
        info = session.store.find(resume) if resume and session.store is not None else None
        if info is not None:
            self.ui.info(resume_text(session, info))

    def open_project(self, path: str) -> str | None:
        """Switch to a project used before. Only those: the page can't point the agent at any folder it names."""
        known = {p["path"] for p in ChatStore.projects(config.USER_DIR)}
        if not isinstance(path, str) or path not in known or not Path(path).is_dir():
            return "that isn't a project you have used here; start one with harness --web --workspace FOLDER"
        ok = self.send(f"opening the project {path} ...", lambda: self.replace(Path(path), {}))
        return None if ok else "a request is running"

    def connect(self, provider, model, base_url) -> str | None:
        """Another provider or model, for this project; the chat carries on. API keys come only from environment variables."""
        if provider not in PROVIDERS:
            return f"choose a provider from: {', '.join(PROVIDERS)}"
        if not isinstance(model, str) or len(model) > 200 or not isinstance(base_url, str) or len(base_url) > 300:
            return "the model and the address must be short text"
        if base_url and not base_url.startswith(("http://", "https://")):
            return "the address must start with http:// or https://"
        chat = self.session.chat
        resume = chat.id if chat is not None and chat.path.exists() else None
        overrides = {"provider": provider, "model": model.strip() or None, "base_url": base_url.strip() or None}
        ok = self.send(f"connecting to {provider} · {model.strip() or 'its default model'} ...",
                       lambda: self.replace(self.session.ws.root, overrides, resume))
        return None if ok else "a request is running"

    def chats_json(self) -> dict:
        s = self.session
        return {"current": s.chat.id if s.chat else None, "saving": s.store is not None, "workspace": str(s.ws.root),
                "chats": [{"id": i.id, "title": i.title or "(no title)", "age": i.age(), "messages": i.messages, "model": i.model}
                          for i in s.chats()[:100]],
                "projects": [{"path": p["path"], "name": p.get("name", ""), "current": Path(p["path"]) == s.ws.root}
                             for p in ChatStore.projects(config.USER_DIR)[:50]]}

    def journal_json(self) -> dict:
        s = self.session
        doc = s.journal.read()
        return {"mode": s.settings.journal, "active": s.journal_active(), "exists": doc is not None,
                "updated": doc.updated if doc else None, "by": doc.updated_by if doc else None,
                "tainted": doc.tainted if doc else False, "body": redacted(doc.body) if doc else ""}

    def settings_json(self) -> dict:
        s = self.session
        return {"provider": s.settings.provider, "model": s.provider.model, "base_url": s.settings.base_url or "",
                "providers": [{"name": p, "key": key_variable(p), "key_set": bool(key_variable(p) and os.environ.get(key_variable(p)))}
                              for p in PROVIDERS],
                "models": ollama_models(s.settings.base_url) if s.settings.provider == "ollama" else [],
                "styles": list(s.styles), "style": s.style.name, "context_window": s.context.window, "config": describe(s.settings)}

    def stop(self) -> bool:
        if not self.busy:
            return False
        self.ui.stop.set()       # ponytail: noticed at the next event, so a long shell command finishes first; a thread can't be killed safely
        self.ui.cancel()         # a question waiting for you is answered no
        return True

    def status(self) -> dict:
        return self.session.status() | {"busy": self.busy}

    def state(self) -> dict:
        last = self.ui.hub.last                     # read first: an event after this is in the stream, not lost
        s = self.session
        tasks = [{"id": t.id, "command": t.command, "text": t.describe(), "running": t.running}
                 for t in (s.tasks.tasks.values() if s.tasks else [])]
        return {"status": self.status(), "messages": self.notes + transcript(list(s.agent.messages)), "last_event": last,
                "todos": s.todos.as_data(), "tasks": tasks, "question": self.ui.question.payload if self.ui.question else None,
                "chat": {"id": s.chat.id, "title": s.chat.title} if s.chat else None}


class Server(ThreadingHTTPServer):
    daemon_threads = True            # an open event stream doesn't keep the process alive
    allow_reuse_address = os.name != "nt"     # on Windows SO_REUSEADDR lets a second server bind the same port (measured)

    def server_bind(self):
        if os.name == "nt":                  # ... and this stops anything else binding ours
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, app: WebApp, port: int):
        super().__init__(("127.0.0.1", port), Handler)      # this computer only
        self.app, self.key, self.closing = app, secrets.token_urlsafe(24), False
        port = self.server_port
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.cookie = f"harness_key_{port}"                   # cookies don't separate ports: two servers mustn't share one
        self.url = f"http://127.0.0.1:{port}/?key={self.key}"


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = "harness"

    def log_message(self, format, *args):           # quiet: the terminal is for the server's address and errors
        pass

    # --- who may ask ---------------------------------------------------------------------------------
    def allowed(self, url) -> bool:
        """The Host must be this server (a web page can make a name resolve to 127.0.0.1: DNS rebinding), and the request must
        carry the key: as the cookie, or in the address on the first visit, which swaps it for the cookie."""
        if self.headers.get("Host") not in self.server.hosts:
            self.reply(403, "text/plain; charset=utf-8", b"wrong Host: open the address the server printed")
            return False
        given = parse_qs(url.query).get("key", [""])[0]
        if url.path == "/" and given and secrets.compare_digest(given, self.server.key):
            self.send_response(303)                    # the key leaves the address bar and the history
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{self.server.cookie}={self.server.key}; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            return False
        cookie = SimpleCookie(self.headers.get("Cookie", "")).get(self.server.cookie)
        if cookie is None or not secrets.compare_digest(cookie.value, self.server.key):
            self.reply(401, "text/plain; charset=utf-8",
                       b"This page needs the key: open the address the server printed in its terminal (it ends with ?key=...).")
            return False
        return True

    # --- answers -------------------------------------------------------------------------------------
    def reply(self, code: int, kind: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def json(self, data, code: int = 200) -> None:
        self.reply(code, "application/json", json.dumps(data, ensure_ascii=False, default=str).encode())

    def do_GET(self):
        url = urlparse(self.path)
        if not self.allowed(url):
            return
        if url.path == "/":
            return self.static("index.html")
        if url.path.startswith("/static/"):
            return self.static(url.path[len("/static/"):])
        if url.path == "/api/state":
            return self.json(self.server.app.state())
        if url.path == "/events":
            return self.events(url)
        if url.path in ("/api/chats", "/api/journal", "/api/settings"):
            app = self.server.app
            return self.json({"/api/chats": app.chats_json, "/api/journal": app.journal_json, "/api/settings": app.settings_json}[url.path]())
        if url.path in ("/api/files", "/api/file"):
            path = parse_qs(url.query).get("path", [""])[0]
            try:
                return self.json((folder_json if url.path == "/api/files" else file_json)(self.server.app.session.ws, path))
            except PermissionError as e:                  # outside the workspace (OutsideWorkspace), or the system said no
                return self.json({"error": str(e)}, 403)
            except OSError as e:
                return self.json({"error": str(e)}, 404)
        self.reply(404, "text/plain", b"not found")

    def do_POST(self):
        url = urlparse(self.path)
        if not self.allowed(url):
            return
        try:
            size = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(size) or b"{}") if 0 <= size <= MAX_BODY else None
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return self.json({"error": "send a JSON object"}, 400)
        app = self.server.app
        if url.path == "/api/send":
            text = body.get("text")
            if not isinstance(text, str) or not text.strip():
                return self.json({"error": "nothing to send"}, 400)
            return self.json({"ok": True}) if app.send(text.strip()) else self.json({"error": "a request is running"}, 409)
        if url.path == "/api/stop":
            return self.json({"stopping": app.stop()})
        if url.path in ("/api/project", "/api/connect"):
            why = (app.open_project(body.get("path")) if url.path == "/api/project" else
                   app.connect(body.get("provider"), body.get("model", ""), body.get("base_url", "")))
            return self.json({"ok": True}) if why is None else self.json({"error": why}, 409 if "running" in why else 400)
        if url.path == "/api/answer":
            why = app.ui.reply(body.get("id"), body.get("answer"))
            return self.json({"ok": True}) if why is None else self.json({"error": why}, 409 if "waiting" in why else 400)
        self.reply(404, "text/plain", b"not found")

    def static(self, name: str) -> None:
        if name not in {p.name for p in STATIC.iterdir()}:      # a fixed list: no path in the name can reach another file
            return self.reply(404, "text/plain", b"not found")
        path = STATIC / name
        self.reply(200, TYPES.get(path.suffix, "application/octet-stream"), path.read_bytes())

    def events(self, url) -> None:
        """Server-Sent Events: `id: N` and `data: {json}` per event, until the page goes away."""
        try:
            last = int(self.headers.get("Last-Event-ID") or parse_qs(url.query).get("after", ["0"])[0])
        except ValueError:
            last = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        hub = self.server.app.ui.hub
        try:
            while not self.server.closing:
                batch = hub.after(last, PING)
                chunk = "".join(f"id: {i}\ndata: {data}\n\n" for i, data in batch) or ": ping\n\n"
                if batch:
                    last = batch[-1][0]
                self.wfile.write(chunk.encode())
                self.wfile.flush()
        except OSError:                                   # the page closed: BrokenPipe, ConnectionReset, ConnectionAborted
            pass


def start(session: Session, commands, port: int = DEFAULT_PORT, flags: dict | None = None) -> Server:
    """The server, listening but not yet serving (tests run serve_forever on a thread)."""
    return Server(WebApp(session, commands, flags), port)


def serve(workspace: Path, flags: dict, port: int = DEFAULT_PORT, open_browser: bool = True, fresh: bool = False) -> None:
    """`harness --web`: make the session with the browser as its interface and serve it until Ctrl+C."""
    ui = WebUI(Hub())
    session, commands = build_session(workspace, flags, ui, fresh)
    try:
        server = start(session, commands, port, flags)
    except OSError as e:
        session.close()
        raise OSError(f"can't listen on port {port} ({e.strerror or e}): another program may be using it. Try --web 0 for a free port") from e
    server.app.notes = [json.loads(data) for _, data in ui.hub.events]
    print(f"Agent harness in your browser: {server.url}\n(only this computer can open it; Ctrl+C here stops the server)", flush=True)
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.closing = True
        server.server_close()
        session = server.app.session              # the page may have opened another project or model since
        session.close()
        if session.costs.models:
            print(f"session: {session.costs.summary()}")
