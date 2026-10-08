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

Only this computer can connect (127.0.0.1), the Host header must name it, and every request needs the key.
"""
import json
import os
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

from harness.cli import announce, handle_line
from harness.security.redact import redacted
from harness.session import Session
from harness.tui.latex import render_math
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
            out.append(result_json(m.tool_call_id, m.tool_name, m.content))
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


class WebUI:
    """The Session's ui in the browser: every event and message becomes an event in the hub."""

    def __init__(self, hub: Hub):
        self.hub = hub
        self.stop = threading.Event()      # /api/stop: the next event in the turn's thread raises KeyboardInterrupt
        self.turn: threading.Thread | None = None

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


class WebApp:
    """What the server runs: one session, the hub its events go to, and the request in progress."""

    def __init__(self, session: Session, commands):
        self.session, self.commands, self.ui = session, commands, session.ui
        self.lock = threading.Lock()
        self.keys = SimpleNamespace(watching=nullcontext)      # run_turn's keyboard watcher: the browser has a Stop button instead
        self.notes: list[dict] = []          # what was said before any page was open (the banner, warnings): shown first on every page

    @property
    def busy(self) -> bool:
        return self.ui.turn is not None and self.ui.turn.is_alive()

    def send(self, text: str) -> bool:
        """Start a request (or a command) on a worker thread. False while one is running."""
        with self.lock:
            if self.busy:
                return False
            self.ui.stop.clear()
            self.ui.turn = threading.Thread(target=self.run, args=(text,), name="harness-turn", daemon=True)
            self.ui.turn.start()
            return True

    def run(self, text: str) -> None:
        hub = self.ui.hub
        hub.publish({"type": "user", "text": text})
        hub.publish({"type": "busy", "busy": True})
        try:
            self.session.announce_tasks()          # background tasks that ended since the last request (Lesson 48)
            if not handle_line(self.session, self.keys, self.commands, text):
                self.ui.info("/bye ends a terminal session; here, close the tab (Ctrl+C in the server's terminal stops the server)")
        except KeyboardInterrupt:
            self.ui.error("stopped")
        except Exception as e:                     # a bug in one request mustn't take the server down
            self.ui.error(f"{type(e).__name__}: {e}")
        finally:
            self.ui.stop.clear()
            hub.publish({"type": "busy", "busy": False, "status": self.session.status() | {"busy": False}})   # this thread is still alive

    def stop(self) -> bool:
        if not self.busy:
            return False
        self.ui.stop.set()       # ponytail: noticed at the next event, so a long shell command finishes first; a thread can't be killed safely
        return True

    def status(self) -> dict:
        return self.session.status() | {"busy": self.busy}

    def state(self) -> dict:
        last = self.ui.hub.last                     # read first: an event after this is in the stream, not lost
        s = self.session
        tasks = [{"id": t.id, "command": t.command, "text": t.describe(), "running": t.running}
                 for t in (s.tasks.tasks.values() if s.tasks else [])]
        return {"status": self.status(), "messages": self.notes + transcript(list(s.agent.messages)), "last_event": last,
                "todos": s.todos.as_data(), "tasks": tasks}


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


def start(session: Session, commands, port: int = DEFAULT_PORT) -> Server:
    """The server, listening but not yet serving (tests run serve_forever on a thread)."""
    return Server(WebApp(session, commands), port)


def serve(settings, ws, commands, styles, port: int = DEFAULT_PORT, open_browser: bool = True, fresh: bool = False) -> None:
    """`harness --web`: make the session with the browser as its interface and serve it until Ctrl+C."""
    ui = WebUI(Hub())
    session = Session(settings, ws, ui, None, styles, interface="web", fresh=fresh)   # no approver yet: asking calls are refused (Lesson 55)
    session.commands = commands
    try:
        server = start(session, commands, port)
    except OSError as e:
        session.close()
        raise OSError(f"can't listen on port {port} ({e.strerror or e}): another program may be using it. Try --web 0 for a free port") from e
    ui.banner("Agent harness", f"{settings.provider} · {session.provider.model} · {ws.root}")
    announce(session)
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
        session.close()
        if session.costs.models:
            print(f"session: {session.costs.summary()}")
