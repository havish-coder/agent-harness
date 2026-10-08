"""Lesson 53: the web server. A real server on a free port, a scripted model that streams, and httpx as the browser."""
import json
import threading
import time

import httpx
import pytest

from harness import config
from harness.agent import NO_APPROVER
from harness.cli import parse_args
from harness.commands import load_commands
from harness.config import Settings
from harness.context.tokens import Breakdown, ContextStatus
from harness.messages import Message, Reply, ToolCall, Usage
from harness.providers.base import TextDelta
from harness.session import Session
from harness.web import DEFAULT_PORT
from harness.web.server import Hub, WebUI, event_json, start
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

    def make(replies, delay=0.0, **settings):
        monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
        root = tmp_path / "proj"
        root.mkdir(exist_ok=True)
        base = {"save_chats": False, "auto_memory": "off", "journal": "off", "file_history": False, "todo": False}
        session = Session(Settings(**(base | settings)), Workspace(root), WebUI(Hub()), None, interface="web")
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
    stranger = httpx.Client(base_url=w.base)
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


def test_a_call_that_needs_approval_is_refused_until_the_page_can_ask(web, tmp_path):
    """Fail-closed: there is no approver yet (Lesson 55 adds one), so a call that would ask doesn't run."""
    w = web([wants(ToolCall("c1", "write_file", {"path": "a.txt", "content": "x"})), answer("I couldn't.")])
    w.send("write a.txt")
    result = next(e for e in w.events() if e["type"] == "tool_result")
    assert result["text"] == NO_APPROVER and result["error"] and not (tmp_path / "proj" / "a.txt").exists()


def test_one_request_at_a_time(web):
    w = web([answer("x" * 150)], delay=0.01)
    assert w.send("first").status_code == 200
    second = w.send("second")
    assert second.status_code == 409 and "running" in second.json()["error"]
    w.events()
    assert w.client.post("/api/send", content=b"not json").status_code == 400
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
