"""Lessons 53-57: the web server. A real server on a free port, a scripted model that streams, and httpx as the browser."""
import json
import os
import re
import socket
import threading
import time
import webbrowser

import httpx
import pytest

from harness import config
from harness.agent import NO_APPROVER
from harness.chats import ChatStore
from harness.cli import parse_args
from harness.commands import load_commands
from harness.config import Settings
from harness.context.tokens import Breakdown, ContextStatus
from harness.messages import Message, Reply, ToolCall, Usage
from harness.providers.base import TextDelta
from harness.session import Session
from harness.web import DEFAULT_PORT
from harness.web.server import (
    STATIC,
    Hub,
    WebApprover,
    WebUI,
    check_answer,
    event_json,
    ollama_models,
    open_page,
    start,
)
from harness.workspace import Workspace


class Streamer:
    """A model that streams its scripted replies a few characters at a time, `delay` seconds apart."""
    model = "streamer"

    def __init__(self, replies, delay=0.0):
        self.replies, self.delay = list(replies), delay

    def chat(self, messages, tools):
        return self.replies.pop(0)

    def stream(self, messages, tools):
        reply = self.replies.pop(0)
        text = reply.message.content
        for i in range(0, len(text), 3):
            time.sleep(self.delay)
            yield TextDelta(text[i:i + 3])
        yield reply


def answer(text):
    return Reply(Message("assistant", text), "end", Usage(10, 5))


def wants(*calls):
    return Reply(Message("assistant", tool_calls=list(calls)), "tool_calls", Usage(10, 5))


class Web:
    def __init__(self, server, session):
        self.server, self.session = server, session
        self.base = f"http://127.0.0.1:{server.server_port}"
        self.client = httpx.Client(base_url=self.base, timeout=10)
        assert self.client.get(server.url).status_code == 303          # the key becomes a cookie

    def send(self, text):
        return self.client.post("/api/send", json={"text": text})

    def events(self, after=0, until=lambda e: e["type"] == "busy" and not e["busy"], headers=None):
        """Read the stream from `after` until an event matches `until` (by default: the request finished)."""
        got = []
        with self.client.stream("GET", f"/events?after={after}", headers=headers or {}) as r:
            assert r.headers["content-type"] == "text/event-stream"
            event_id = None
            for line in r.iter_lines():
                if line.startswith("id: "):
                    event_id = int(line[4:])
                elif line.startswith("data: "):
                    got.append(json.loads(line[6:]) | {"_id": event_id})
                    if until(got[-1]):
                        return got
        return got


@pytest.fixture
def web(tmp_path, monkeypatch):
    servers = []

    def make(replies, delay=0.0, approver=True, **settings):
        monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
        root = tmp_path / "proj"
        root.mkdir(exist_ok=True)
        base = {"save_chats": False, "auto_memory": "off", "journal": "off", "file_history": False, "todo": False}
        ui = WebUI(Hub())
        session = Session(Settings(**(base | settings)), Workspace(root), ui, WebApprover(ui) if approver else None, interface="web")
        session.agent.provider = Streamer(replies, delay)
        server = start(session, load_commands(root), port=0)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        servers.append(server)
        return Web(server, session)
    yield make
    for server in servers:
        server.closing = True
        server.shutdown()
        server.server_close()


# --- who may connect ---------------------------------------------------------------------------------------------

def test_the_server_listens_on_this_computer_only_and_the_page_needs_the_key(web):
    w = web([])
    assert w.server.server_address[0] == "127.0.0.1"
    stranger = httpx.Client(base_url=w.base, timeout=10)
    assert stranger.get("/").status_code == 401 and stranger.get("/events").status_code == 401
    assert stranger.get("/?key=wrong").status_code == 401 and stranger.post("/api/send", json={"text": "hi"}).status_code == 401
    first = stranger.get(w.server.url)
    assert first.status_code == 303 and first.headers["location"] == "/"          # the key leaves the address bar
    cookie = first.headers["set-cookie"]
    assert cookie.startswith(f"harness_key_{w.server.server_port}=") and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    page = stranger.get("/")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html") and "app.js" in page.text
    assert stranger.get("/static/app.js").headers["content-type"].startswith("text/javascript")
    for name in ("server.py", "..%2Fserver.py", "..%5Cserver.py", "nothing.js"):
        assert stranger.get(f"/static/{name}").status_code == 404


def test_a_second_server_cannot_take_the_same_port(web):
    w = web([])
    with pytest.raises(OSError):
        start(w.session, load_commands(w.session.ws.root), port=w.server.server_port)


def test_every_answer_carries_the_security_headers(web):
    """Lesson 57: no framing (a Yes clicked through an invisible frame), nothing loaded but our own files, no sniffing, no referrer."""
    w = web([])
    for path in ("/", "/static/app.js", "/api/state"):
        h = w.client.get(path).headers
        assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"
        csp = h["content-security-policy"]
        assert "frame-ancestors 'none'" in csp and "script-src 'self'" in csp and "unsafe" not in csp and "default-src 'none'" in csp
        assert "access-control-allow-origin" not in h
    assert "x-frame-options" in httpx.get(f"{w.base}/").headers                    # refusals too (401 without the key)


def test_the_page_needs_nothing_the_policy_forbids():
    """The CSP allows only our own files: no inline script or style, no outside address, in the page we ship."""
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert all('src="/static/' in tag for tag in re.findall(r"<script[^>]*>", page)) and "<style" not in page and " style=" not in page
    assert "http" not in page and not re.search(r"\son[a-z]+\s*=", page)               # no outside address, no onclick= handlers
    for name in ("app.js", "markdown.js"):
        code = (STATIC / name).read_text(encoding="utf-8")
        assert "eval(" not in code and "new Function" not in code and 'setAttribute("style"' not in code


def test_a_post_from_another_origin_or_an_html_form_is_refused(web):
    """SameSite=Strict keeps the cookie off other sites' requests; for a browser that ignores it, Origin and the content type hold."""
    w = web([answer("hi")])
    assert w.client.post("/api/send", json={"text": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert w.client.post("/api/send", json={"text": "x"}, headers={"Origin": "null"}).status_code == 403
    form = w.client.post("/api/send", content=json.dumps({"text": "x"}), headers={"Content-Type": "text/plain"})
    assert form.status_code == 415
    assert w.client.post("/api/stop", data={"a": "b"}).status_code == 415                       # application/x-www-form-urlencoded
    cookie = f"{w.server.cookie}={w.server.key}"                                   # a raw request: it claims 5 MB and sends none of it
    with socket.create_connection(("127.0.0.1", w.server.server_port), timeout=5) as raw:
        raw.sendall(f"POST /api/send HTTP/1.1\r\nHost: 127.0.0.1:{w.server.server_port}\r\nCookie: {cookie}\r\n"
                    "Content-Type: application/json\r\nContent-Length: 5000000\r\n\r\n".encode())
        assert raw.recv(64).startswith(b"HTTP/1.0 413")                             # answered at once, the body never read
    stranger = httpx.Client(base_url=w.base, timeout=10)
    for _ in range(30):          # a refusal with the body left unread reset the connection on Windows: the client saw no answer
        assert stranger.post("/api/send", json={"text": "x" * 200_000}).status_code == 401
        assert w.client.post("/api/send", json={"text": "x" * 200_000}, headers={"Origin": "https://evil.example"}).status_code == 403
    own = w.client.post("/api/send", json={"text": "hello"}, headers={"Origin": f"http://localhost:{w.server.server_port}"})
    assert own.status_code == 200
    w.events()


def test_the_browser_is_opened_without_the_key_on_its_command_line(monkeypatch):
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url))
    page = open_page("http://127.0.0.1:8765/?key=SECRET-KEY")
    try:
        assert len(opened) == 1 and opened[0].startswith("file:") and "SECRET-KEY" not in opened[0]
        text = page.read_text(encoding="utf-8")
        assert 'content="0;url=http://127.0.0.1:8765/?key=SECRET-KEY"' in text
        if os.name != "nt":
            assert page.stat().st_mode & 0o077 == 0                       # readable by you only
    finally:
        page.unlink()


def test_a_host_header_naming_another_site_is_refused_even_with_the_key(web):
    """DNS rebinding: a page on evil.example makes its name resolve to 127.0.0.1; the browser then sends Host: evil.example."""
    w = web([])
    for host in ("evil.example", f"evil.example:{w.server.server_port}", "127.0.0.1:1"):
        assert w.client.get("/api/state", headers={"Host": host}).status_code == 403
    assert w.client.get("/api/state", headers={"Host": f"localhost:{w.server.server_port}"}).status_code == 200


# --- a request, live -------------------------------------------------------------------------------------------------

def test_a_request_streams_its_events_in_order(web):
    w = web([answer("Hello from the agent, streamed in pieces.")])
    assert w.send("hi").json() == {"ok": True}
    got = w.events()
    kinds = [e["type"] for e in got]
    assert kinds[:4] == ["user", "busy", "context", "model_call"] and kinds[-3:] == ["answer", "usage", "busy"]
    assert "".join(e["text"] for e in got if e["type"] == "text_delta") == "Hello from the agent, streamed in pieces."
    assert got[0]["text"] == "hi" and got[-1]["status"]["busy"] is False and got[-1]["status"]["turns"] == 1
    assert [e["_id"] for e in got] == list(range(got[0]["_id"], got[0]["_id"] + len(got)))      # numbered without gaps


def test_tool_calls_and_their_results_reach_the_page(web, tmp_path):
    w = web([wants(ToolCall("c1", "list_dir", {"path": "."})), answer("One file.")])
    (tmp_path / "proj" / "notes.txt").write_text("x")
    w.send("what is here?")
    got = w.events()
    call = next(e for e in got if e["type"] == "tool_call")
    result = next(e for e in got if e["type"] == "tool_result")
    assert (call["id"], call["name"], call["args"]) == ("c1", "list_dir", {"path": "."})
    assert result["id"] == "c1" and "notes.txt" in result["text"] and result["error"] is False


def test_without_an_approver_a_call_that_would_ask_is_refused(web, tmp_path):
    """Fail-closed: a session made without one (a script) refuses the call instead of waiting for ever."""
    w = web([wants(ToolCall("c1", "write_file", {"path": "a.txt", "content": "x"})), answer("I couldn't.")], approver=False)
    w.send("write a.txt")
    result = next(e for e in w.events() if e["type"] == "tool_result")
    assert result["text"] == NO_APPROVER and result["error"] and not (tmp_path / "proj" / "a.txt").exists()


def test_one_request_at_a_time(web):
    w = web([answer("x" * 150)], delay=0.01)
    assert w.send("first").status_code == 200
    second = w.send("second")
    assert second.status_code == 409 and "running" in second.json()["error"]
    w.events()
    assert w.client.post("/api/send", content=b"not json", headers={"Content-Type": "application/json"}).status_code == 400
    assert w.send("   ").status_code == 400


def test_stop_ends_the_request_and_rolls_it_back(web):
    w = web([answer("word " * 200)], delay=0.01)
    w.send("write a lot")
    w.events(until=lambda e: e["type"] == "text_delta")
    assert w.client.post("/api/stop", json={}).json() == {"stopping": True}
    got = w.events()
    assert {"type": "error", "text": "cancelled"} in [{k: v for k, v in e.items() if k != "_id"} for e in got]
    assert [m.role for m in w.session.agent.messages] == ["system"] and w.session.agent.stop_reason == "cancelled"
    assert w.client.post("/api/stop", json={}).json() == {"stopping": False}      # nothing running


def test_a_page_that_reconnects_gets_what_it_missed_and_the_state_holds_the_conversation(web):
    w = web([answer("First answer."), answer("Second answer.")])
    w.send("one")
    first = w.events()
    middle = first[len(first) // 2]["_id"]
    again = w.events(headers={"Last-Event-ID": str(middle)})          # what EventSource sends when it reconnects
    assert again[0]["_id"] == middle + 1 and [e["_id"] for e in again] == [e["_id"] for e in first if e["_id"] > middle]
    state = w.client.get("/api/state").json()
    assert [(m["type"], m["text"]) for m in state["messages"]] == [("user", "one"), ("answer", "First answer.")]
    assert state["last_event"] == first[-1]["_id"] and state["status"]["busy"] is False


def test_slash_commands_work_in_the_page(web):
    w = web([])
    for line, kind, words in (("/cost", "info", ""), ("/nope", "warn", "unknown command /nope"), ("/bye", "info", "close the tab")):
        after = w.client.get("/api/state").json()["last_event"]
        w.send(line)
        said = [e for e in w.events(after=after) if e["type"] in ("info", "warn")]
        assert said and said[0]["type"] == kind and words in said[0]["text"]


# --- questions from the agent (Lesson 55) ---------------------------------------------------------------------------

def without_ids(events):
    return [{k: v for k, v in e.items() if k != "_id"} for e in events]


def asked(w, after=0):
    return w.events(after=after, until=lambda e: e["type"] == "question")[-1]


def reply(w, q, value):
    return w.client.post("/api/answer", json={"id": q["id"], "answer": value})


def test_an_approval_shows_the_diff_and_yes_runs_the_call(web, tmp_path):
    w = web([wants(ToolCall("c1", "write_file", {"path": "a.txt", "content": "hello\n"})), answer("Done.")])
    w.send("write a.txt")
    q = asked(w)
    assert (q["kind"], q["tool"], q["call_id"], q["args"]["path"]) == ("approval", "write_file", "c1", "a.txt")
    assert "new file a.txt" in q["preview"] and "+hello" in q["preview"] and q["always"] == "every write_file call"
    assert w.client.get("/api/state").json()["question"]["id"] == q["id"]          # a page that opens now sees it too
    assert reply(w, q, "yes").json() == {"ok": True}
    got = w.events(after=q["_id"])
    assert {"type": "answered", "id": q["id"], "answer": "yes"} in without_ids(got)
    assert not next(e for e in got if e["type"] == "tool_result")["error"] and (tmp_path / "proj" / "a.txt").read_text() == "hello\n"
    assert w.client.get("/api/state").json()["question"] is None


def test_no_denies_the_call_and_only_the_first_answer_counts(web, tmp_path):
    w = web([wants(ToolCall("c1", "write_file", {"path": "a.txt", "content": "x"})), answer("OK, I won't.")])
    w.send("write a.txt")
    q = asked(w)
    assert reply(w, q, "maybe").status_code == 400 and w.client.post("/api/answer", json={"id": "q99", "answer": "yes"}).status_code == 409
    assert reply(w, q, "no").status_code == 200
    assert reply(w, q, "yes").status_code == 409                                       # another tab, too late
    got = w.events(after=q["_id"])
    assert any(e["type"] == "tool_denied" for e in got) and not (tmp_path / "proj" / "a.txt").exists()


def test_always_allows_the_rest_of_the_session_without_asking(web, tmp_path):
    w = web([wants(ToolCall("c1", "write_file", {"path": "a.txt", "content": "1"})),
             wants(ToolCall("c2", "write_file", {"path": "b.txt", "content": "2"})), answer("Both written.")])
    w.send("write two files")
    q = asked(w)
    reply(w, q, "always")
    got = w.events(after=q["_id"])
    assert [e["type"] for e in got].count("question") == 0 and (tmp_path / "proj" / "b.txt").read_text() == "2"


def test_stop_while_the_agent_waits_answers_no_and_rolls_back(web, tmp_path):
    w = web([wants(ToolCall("c1", "write_file", {"path": "a.txt", "content": "x"})), answer("never sent")])
    w.send("write a.txt")
    q = asked(w)
    assert w.client.post("/api/stop", json={}).json() == {"stopping": True}
    got = without_ids(w.events(after=q["_id"]))
    assert {"type": "answered", "id": q["id"], "answer": "no"} in got and {"type": "error", "text": "cancelled"} in got
    assert not (tmp_path / "proj" / "a.txt").exists() and [m.role for m in w.session.agent.messages] == ["system"]


def test_the_agents_questions_are_answered_from_the_page(web):
    w = web([wants(ToolCall("c1", "ask_user", {"question": "Which discount?", "options": ["10%", "20%"]})),
             wants(ToolCall("c2", "ask_user", {"question": "Your favourite colour?"})), answer("Thanks.")])
    w.send("set up the shop")
    choice = asked(w)
    assert choice["kind"] == "choice" and choice["question"] == "The agent asks: Which discount?"
    assert choice["options"] == {"1": "10%", "2": "20%", "t": "something else (type it)"}
    assert reply(w, choice, "9").status_code == 400 and reply(w, choice, "2").status_code == 200
    text = asked(w, after=choice["_id"])
    assert text["kind"] == "text" and reply(w, text, 42).status_code == 400 and reply(w, text, "blue").status_code == 200
    got = w.events(after=text["_id"])
    assert [e["text"] for e in got if e["type"] == "tool_result"] == ["The user answered: blue"]
    assert {"type": "answered", "id": text["id"], "answer": True} in without_ids(got)          # typed text isn't sent to every page
    assert next(m for m in w.session.agent.messages if m.role == "tool").content == "The user answered: 20%"


def test_a_plan_is_shown_and_approved_in_the_page(web):
    plan = "Goal: fix the cart.\n1. Edit shop/cart.py: multiply by quantity\n2. Run the tests"
    w = web([wants(ToolCall("c1", "exit_plan_mode", {"plan": plan})), answer("Starting.")], todo=True)
    w.session.set_mode("plan")
    w.send("plan the fix")
    upto = w.events(until=lambda e: e["type"] == "question")
    q, shown = upto[-1], next(e for e in upto if e["type"] == "plan")
    assert shown["text"] == plan and q["question"] == "Go ahead with this plan?" and set(q["options"]) == {"y", "a", "n", "f"}
    reply(w, q, "y")
    w.events(after=q["_id"])
    assert w.session.permissions.mode == "default"
    assert [t.content for t in w.session.todos.items] == ["Edit shop/cart.py: multiply by quantity", "Run the tests"]


def test_a_reloaded_page_shows_results_without_the_fence_the_model_read(web, tmp_path):
    """Results in the conversation are fenced for the model (Lesson 31); live, the page gets them plain, and a reload must too."""
    w = web([wants(ToolCall("c1", "read_file", {"path": "notes.txt"})), answer("Read it.")], fence_untrusted=True)
    (tmp_path / "proj" / "notes.txt").write_text("hello")
    w.send("read notes.txt")
    w.events()
    assert "<untrusted" in next(m for m in w.session.agent.messages if m.role == "tool").content       # what the model read
    shown = next(e for e in w.client.get("/api/state").json()["messages"] if e["type"] == "tool_result")["text"]
    assert "<untrusted" not in shown and "hello" in shown


def test_what_an_answer_must_be():
    approval = {"kind": "approval", "always": None}
    assert check_answer(approval, "yes") is None and check_answer(approval, "always") and check_answer(approval | {"always": "x"}, "always") is None
    assert check_answer({"kind": "choice", "options": {"1": "a"}}, "") is None and check_answer({"kind": "text"}, "x" * 5000)


# --- chats, projects, the journal and the model (Lesson 56) ------------------------------------------------------------

def done(w, text):
    """Send `text` and wait for that request to end (from the events after it, not an earlier request's end)."""
    after = w.client.get("/api/state").json()["last_event"]
    assert w.send(text).status_code == 200
    return without_ids(w.events(after=after))


def test_chats_are_listed_and_a_new_chat_or_a_resumed_one_redraws_the_page(web):
    w = web([answer("First."), answer("Second.")], save_chats=True)
    done(w, "first chat")
    chats = w.client.get("/api/chats").json()
    assert chats["saving"] and [c["title"] for c in chats["chats"]] == ["first chat"] and chats["current"] == chats["chats"][0]["id"]
    first_id = chats["current"]
    assert {"type": "conversation"} in done(w, "/reset")                     # pages draw the (empty) conversation again
    assert all(m["type"] != "answer" for m in w.client.get("/api/state").json()["messages"])
    done(w, "second chat")
    assert {"type": "conversation"} in done(w, f"/resume {first_id}")
    state = w.client.get("/api/state").json()
    assert [(m["type"], m["text"]) for m in state["messages"] if m["type"] in ("user", "answer")][-2:] == [("user", "first chat"), ("answer", "First.")]
    assert state["chat"]["id"] == first_id


def test_a_project_is_opened_only_if_it_was_used_before(web, tmp_path):
    w = web([])
    other = tmp_path / "other"
    other.mkdir()
    assert w.client.post("/api/project", json={"path": str(other)}).status_code == 400            # never used: refused
    assert w.client.post("/api/project", json={"path": "C:/Windows"}).status_code == 400
    ChatStore(config.USER_DIR, other).register()
    listed = w.client.get("/api/chats").json()["projects"]
    assert str(other.resolve()) in [p["path"] for p in listed]
    after = w.client.get("/api/state").json()["last_event"]
    assert w.client.post("/api/project", json={"path": str(other.resolve())}).json() == {"ok": True}
    got = without_ids(w.events(after=after))
    assert {"type": "conversation"} in got
    state = w.client.get("/api/state").json()
    assert state["status"]["workspace"] == str(other.resolve()) and any("other" in m.get("text", "") for m in state["messages"] if m["type"] == "info")


def test_connecting_another_model_keeps_the_chat_and_never_takes_a_key(web, monkeypatch):
    w = web([answer("Hello.")], save_chats=True)
    w.send("hi")
    w.events()
    for bad in ({"provider": "nope", "model": "x"}, {"provider": "ollama", "model": "x", "base_url": "file:///etc/passwd"},
                {"provider": "ollama", "model": "x" * 300}):
        assert w.client.post("/api/connect", json=bad).status_code == 400
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    after = w.client.get("/api/state").json()["last_event"]
    w.client.post("/api/connect", json={"provider": "openai", "model": "gpt-x", "base_url": ""})
    got = without_ids(w.events(after=after))
    assert any(e["type"] == "error" and "OPENAI_API_KEY" in e["text"] for e in got)                 # said why; the old session goes on
    assert w.session.provider.model == "streamer" or w.server.app.session is w.session
    after = w.client.get("/api/state").json()["last_event"]
    assert w.client.post("/api/connect", json={"provider": "ollama", "model": "qwen3:8b", "base_url": ""}).json() == {"ok": True}
    w.events(after=after)
    app = w.server.app
    assert app.session is not w.session and app.session.provider.model == "qwen3:8b" and app.flags["model"] == "qwen3:8b"
    assert [m.content for m in app.session.agent.messages if m.role == "user"] == ["hi"]          # the chat carried on
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key-123456")
    settings = w.client.get("/api/settings").json()
    openai = next(p for p in settings["providers"] if p["name"] == "openai")
    assert openai == {"name": "openai", "key": "OPENAI_API_KEY", "key_set": True}
    assert "sk-test-not-a-real-key" not in json.dumps(settings) and settings["model"] == "qwen3:8b"


def test_the_journal_is_shown_with_secrets_hidden(web, tmp_path):
    w = web([], journal="ask")
    assert w.client.get("/api/journal").json()["exists"] is False
    from harness.journal import SECTIONS
    body = "\n\n".join(f"# {s}\n{s} text" for s in SECTIONS).replace("Goal text", "Goal text sk-ant-" + "b" * 30)
    (tmp_path / "proj" / ".harness").mkdir(exist_ok=True)
    (tmp_path / "proj" / ".harness" / "progress.md").write_text(body, encoding="utf-8")
    journal = w.client.get("/api/journal").json()
    assert journal["exists"] and journal["active"] and "# Done so far" in journal["body"] and "sk-ant-" not in journal["body"]


def test_ollamas_models_are_listed_and_a_server_that_doesnt_answer_lists_none():
    assert ollama_models("http://127.0.0.1:9") == []


# --- the explorer and the file viewer (Lesson 54) --------------------------------------------------------------------

def test_the_explorer_lists_what_list_dir_would_and_stays_in_the_workspace(web, tmp_path):
    w = web([])
    root = tmp_path / "proj"
    for name in ("src/app.py", "notes.txt", ".git/config", "node_modules/x.js"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("x")
    top = w.client.get("/api/files").json()
    assert [(e["name"], e["dir"]) for e in top["entries"]] == [("src", True), ("notes.txt", False)]      # folders first; .git skipped
    assert w.client.get("/api/files", params={"path": "src"}).json()["entries"] == [{"name": "app.py", "path": "src/app.py", "dir": False}]
    for outside in ("..", "../..", str(tmp_path), "C:/Windows"):
        assert w.client.get("/api/files", params={"path": outside}).status_code == 403
    assert w.client.get("/api/files", params={"path": "missing"}).status_code == 404


def test_the_viewer_shows_text_with_secrets_hidden_and_only_inside_the_workspace(web, tmp_path):
    w = web([])
    root = tmp_path / "proj"
    (root / "app.py").write_text('KEY = "sk-ant-' + "a" * 30 + '"\nprint(1)\n')
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    (root / "big.txt").write_text("x" * 300_000)
    (tmp_path / "secret.txt").write_text("outside")
    shown = w.client.get("/api/file", params={"path": "app.py"}).json()
    assert shown["path"] == "app.py" and "print(1)" in shown["text"] and "sk-ant-" not in shown["text"] and shown["truncated"] is False
    assert w.client.get("/api/file", params={"path": "logo.png"}).json() == {"path": "logo.png", "binary": True}
    big = w.client.get("/api/file", params={"path": "big.txt"}).json()
    assert big["truncated"] and len(big["text"]) == 200_000
    assert w.client.get("/api/file", params={"path": "../secret.txt"}).status_code == 403
    assert w.client.get("/api/file", params={"path": "."}).status_code == 404


def test_the_state_carries_the_todo_list_and_the_background_tasks(web):
    w = web([])
    w.session.todos.items = []
    state = w.client.get("/api/state").json()
    assert state["todos"] == [] and state["tasks"] == []


def test_the_page_and_its_files_are_served(web):
    w = web([])
    page = w.client.get("/").text
    for name in ("app.js", "markdown.js", "app.css", "icon.svg"):
        assert name in page or name == "app.css" and name in page
        assert w.client.get(f"/static/{name}").status_code == 200
    assert w.client.get("/static/icon.svg").headers["content-type"] == "image/svg+xml"


# --- the pieces --------------------------------------------------------------------------------------------------------

def test_every_agent_event_becomes_json_or_is_skipped():
    call = ToolCall("c1", "read_file", {"path": "a.py"})
    status = ContextStatus(100, 90, 1000, 2000, "ok", Breakdown(0, 0, 0, 0))
    samples = {"text_delta": "hi", "tool_call": call, "tool_result": (call, "Error: no"), "tool_denied": call,
               "tool_refused": (call, "plan mode"), "model_reply": answer("x"), "context": status, "todos": [],
               "subagent": ("explore", "tool_call", call), "nudge": "x", "notice": "task ended", "message": Message.user("x")}
    out = {k: event_json(k, v) for k, v in samples.items()}
    assert out["message"] is None and out["tool_result"]["error"] and out["tool_denied"]["reason"] == "you said no"
    assert out["subagent"]["info"]["name"] == "read_file" and out["context"]["level"] == "ok"
    json.dumps(out)


def test_the_hub_keeps_the_newest_events_and_restarts_for_a_page_from_another_server():
    hub = Hub(keep=3)
    for n in range(5):
        hub.publish({"n": n})
    assert [i for i, _ in hub.after(0, 0)] == [3, 4, 5] and hub.after(5, 0) == []
    assert [i for i, _ in hub.after(99, 0)] == [3, 4, 5]


def test_the_flag():
    assert parse_args(["--web"]).web == DEFAULT_PORT and parse_args(["--web", "0"]).web == 0 and parse_args([]).web is None
