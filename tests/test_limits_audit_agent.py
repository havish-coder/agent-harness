"""Lesson 34 inside the agent and session: redacted results, the audit trail, the limits."""
import json

import pytest

from harness import config
from harness.agent import Agent
from harness.audit import verify
from harness.commands import load_commands
from harness.config import ConfigError, Settings, load_settings
from harness.limits import Limits
from harness.messages import ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.security.permissions import Permissions
from harness.session import Session
from harness.tools import default_tools
from harness.tui.plain import PlainApprover, PlainUI
from harness.workspace import Workspace

KEY = "sk-lab-0123456789abcdefghijklmnop"


@pytest.fixture
def ws(tmp_path):
    (tmp_path / ".env").write_text(f"ANTHROPIC_API_KEY={KEY}\nDEBUG=1\n", encoding="utf-8")
    return Workspace(tmp_path)


def read_env(id="1"):
    return ToolCall(id, "read_file", {"path": ".env"})


# --- redaction in the loop -----------------------------------------------------------------

def test_the_model_and_the_screen_see_the_file_without_its_secrets(ws):
    provider = ScriptedProvider([tool_calls(read_env()), text("done")])
    events = []
    Agent(provider, default_tools(ws), "s", stream=False, redact_results=True, permissions=Permissions(ws),
          on_event=lambda k, d: events.append((k, d))).run("go")
    seen = [m.content for m in provider.requests[-1][0] if m.role == "tool"][0]
    assert KEY not in seen and "ANTHROPIC_API_KEY=[REDACTED: api key]" in seen and "DEBUG=1" in seen
    shown = next(d for k, d in events if k == "tool_result")[1]
    assert KEY not in shown
    redacted = next(d for k, d in events if k == "redacted")
    assert redacted[0].name == "read_file" and redacted[1] == ["api key"]


def test_redaction_is_off_unless_asked_for(ws):
    provider = ScriptedProvider([tool_calls(read_env()), text("done")])
    Agent(provider, default_tools(ws), "s", stream=False, permissions=Permissions(ws)).run("go")
    assert KEY in [m.content for m in provider.requests[-1][0] if m.role == "tool"][0]


# --- limits in the loop --------------------------------------------------------------------

def test_a_session_limit_stops_the_loop_and_says_why(ws):
    calls = []
    reasons = iter([None, None, "501 tool calls (limit 500)"])
    provider = ScriptedProvider([tool_calls(ToolCall(str(i), "list_dir", {"path": "."})) for i in range(10)])
    agent = Agent(provider, default_tools(ws), "s", stream=False, permissions=Permissions(ws), max_steps=10,
                  limit_check=lambda: next(reasons), on_event=lambda k, d: calls.append(k))
    answer = agent.run("go")
    assert agent.stop_reason == "limit" and "501 tool calls (limit 500)" in answer and "/limits" in answer
    assert len(provider.requests) == 2 and "limit" in calls          # two model calls, then stopped before the third


# --- the session: audit trail, limits, commands --------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch):
    user = tmp_path / "home" / ".harness"
    monkeypatch.setattr(config, "USER_DIR", user)
    return user


class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.warnings = []

    def warn(self, text_):
        self.warnings.append(text_)


def entries(session):
    return [json.loads(line) for line in session.audit_log.path.read_text(encoding="utf-8").splitlines()]


def scripted_session(ws, replies, settings=None, approver=None):
    session = Session(settings or Settings(), ws, Quiet(), approver or PlainApprover())
    session.agent.provider = ScriptedProvider(replies)
    session.agent.stream = False
    return session


def test_a_chat_leaves_a_readable_audit_trail_without_secrets(home, ws):
    session = scripted_session(ws, [tool_calls(read_env("a"), ToolCall("b", "write_file", {"path": "x.txt", "content": f"k={KEY}"})),
                                    text("done")], approver=lambda call, tool, decision=None: False)
    session.agent.run("go")
    session.close()
    log = entries(session)
    kinds = [e["kind"] for e in log]
    assert kinds[0] == "session" and kinds[-1] == "end"
    assert {"decision", "result", "redacted", "user_denied", "model"} <= set(kinds)
    assert all(e["session"] == session.session_id for e in log)
    decisions = {e["tool"]: e for e in log if e["kind"] == "decision"}
    assert decisions["read_file"]["subject"] == ".env" and decisions["read_file"]["action"] == "allow"
    assert decisions["write_file"]["subject"] == "x.txt" and decisions["write_file"]["action"] == "ask"
    assert next(e for e in log if e["kind"] == "redacted")["kinds"] == ["api key"]
    assert KEY not in session.audit_log.path.read_text(encoding="utf-8")
    assert verify(session.audit_log.path)[0]
    assert log[-1]["tool_calls"] == 2


def test_approvals_modes_and_trust_are_recorded(home, ws):
    session = scripted_session(ws, [tool_calls(ToolCall("a", "write_file", {"path": "x.txt", "content": "x"})), text("done")],
                               approver=lambda call, tool, decision=None: "always")
    session.agent.run("go")
    session.set_mode("accept-edits")
    load_commands(ws.root).parse("/trust")[0].run(session, "")
    load_commands(ws.root).parse("/taint clear")[0].run(session, "clear")
    kinds = {e["kind"]: e for e in entries(session)}
    assert kinds["approved"]["answer"] == "always" and kinds["mode"]["after"] == "accept-edits"
    assert kinds["trust"]["trusted"] is True and "taint_cleared" in kinds


def test_the_audit_log_can_be_turned_off(home, ws):
    session = scripted_session(ws, [text("hi")], Settings(audit_log=False))
    session.agent.run("go")
    session.close()
    assert session.audit_log is None and not (home / "audit").exists()
    assert "audit log is off" in load_commands(ws.root).parse("/audit")[0].run(session, "")


def test_the_audit_command_shows_entries_and_verifies_the_chain(home, ws):
    session = scripted_session(ws, [tool_calls(ToolCall("a", "list_dir", {"path": "."})), text("done")])
    session.agent.run("go")
    audit = load_commands(ws.root).parse("/audit")[0]
    out = audit.run(session, "")
    assert f"session {session.session_id}" in out and "decision" in out and "tool='list_dir'" in out
    assert "chain intact" in audit.run(session, "verify")
    lines = session.audit_log.path.read_text(encoding="utf-8").splitlines()
    session.audit_log.path.write_text("\n".join(lines[:1] + lines[2:]) + "\n", encoding="utf-8")
    assert "BROKEN" in audit.run(session, "verify")


def test_a_chat_that_hits_a_limit_stops_and_reset_starts_again(home, ws):
    settings = Settings(limits={"tool_calls": 2, "cost": None, "tokens": None, "minutes": None})
    replies = [tool_calls(ToolCall(str(i), "list_dir", {"path": "."})) for i in range(10)]
    session = scripted_session(ws, replies, settings)
    answer = session.agent.run("go")
    assert session.agent.stop_reason == "limit" and "2 tool calls (limit 2)" in answer
    assert any(e["kind"] == "limit" and "2 tool calls" in e["why"] for e in entries(session))
    session.reset()
    assert session.limit_reason() is None and session.limits.tool_calls == 0


def test_token_and_cost_limits_use_what_the_session_counted(home, ws):
    session = scripted_session(ws, [text("x")], Settings(limits={"tool_calls": None, "cost": None, "tokens": 100, "minutes": None}))
    session.limits.tokens = 150
    assert session.limit_reason() == "150 tokens used (limit 100)"
    session2 = scripted_session(ws, [text("x")], Settings(limits={"tool_calls": None, "cost": 1.0, "tokens": None, "minutes": None}))
    assert session2.limit_reason() is None                    # no price known for the scripted model: no cost limit


def test_the_limits_command_reports_use_against_each_limit(home, ws):
    session = scripted_session(ws, [tool_calls(ToolCall("a", "list_dir", {"path": "."})), text("done")])
    session.agent.run("go")
    out = load_commands(ws.root).parse("/limits")[0].run(session, "")
    assert "tool calls  1 of 500" in out and "cost" in out and "of $5.00" in out and "tokens" in out and "no limit" in out


def test_a_log_that_cannot_be_written_is_reported_once_and_the_agent_goes_on(home, ws):
    session = scripted_session(ws, [tool_calls(ToolCall("a", "list_dir", {"path": "."})), text("done")])
    session.audit_log.path = home / "audit" / "x" / "blocked"      # make the parent a file
    (home / "audit").mkdir(parents=True, exist_ok=True)
    (home / "audit" / "x").write_text("a file, not a folder", encoding="utf-8")
    assert session.agent.run("go") == "done"
    assert sum("audit log can't be written" in w for w in session.ui.warnings) == 1


# --- settings ------------------------------------------------------------------------------

def test_new_settings_cannot_come_from_a_project(home, tmp_path):
    project = tmp_path / "project"
    (project / ".harness").mkdir(parents=True)
    (project / ".harness" / "settings.json").write_text(json.dumps(
        {"audit_log": False, "redact_secrets": False, "limits": {"cost": 1000}}), encoding="utf-8")
    settings, warnings = load_settings(project, environ={})
    assert settings.audit_log is True and settings.redact_secrets is True and settings.limits["cost"] == 5.0
    assert sum("project settings can't set" in w for w in warnings) == 3


def test_limits_merge_across_layers_and_are_validated(home, tmp_path):
    (home).mkdir(parents=True)
    (home / "settings.json").write_text(json.dumps({"limits": {"cost": 20, "minutes": 90}}), encoding="utf-8")
    settings, _ = load_settings(tmp_path, environ={"HARNESS_LIMITS": json.dumps({"tool_calls": None})})
    assert settings.limits == {"tool_calls": None, "cost": 20, "tokens": None, "minutes": 90}
    for bad, message in [({"limits": {"money": 1}}, "unknown limit"), ({"limits": {"cost": -1}}, "positive number"),
                         ({"limits": {"cost": "5"}}, "positive number"), ({"limits": {"cost": True}}, "positive number")]:
        (home / "settings.json").write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ConfigError, match=message):
            load_settings(tmp_path, environ={})


def test_an_exported_chat_has_no_secrets(ws):
    from harness.export import chat_markdown
    from harness.messages import Message
    md = chat_markdown([Message.user(f"my key is {KEY}"), Message("assistant", f"I saw ANTHROPIC_API_KEY={KEY}")], "t", "m")
    assert KEY not in md and md.count("[REDACTED: api key]") == 2


def test_limits_object_defaults_match_the_settings_defaults():
    from harness.config import DEFAULT_LIMITS
    limits = Limits(**{f"max_{k}": v for k, v in DEFAULT_LIMITS.items()})
    assert (limits.max_tool_calls, limits.max_cost, limits.max_tokens, limits.max_minutes) == (500, 5.0, None, None)
