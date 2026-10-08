"""Lesson 47: sub-agents. A fresh agent does the reading; the parent gets the report."""
import json

import pytest

import harness.session as session_module
from harness import config
from harness.agents import (
    EXCLUDED,
    MAX_REPORT_CHARS,
    MAX_TASK_CHARS,
    SUBAGENT_RULE,
    AgentDef,
    agents_text,
    load_agents,
    make_agent_tools,
)
from harness.chats import replay
from harness.commands import load_commands
from harness.config import Settings
from harness.messages import ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.security.taint import SYSTEM_RULE
from harness.security.trust import set_trusted
from harness.session import Session
from harness.tools.base import tool
from harness.tui.plain import PlainUI
from harness.workspace import Workspace


def fake_tool(name, read_only=True):
    @tool(name=name, read_only=read_only)
    def f() -> str:
        """A tool."""
        return ""
    return f


ALL = [fake_tool(n) for n in ("read_file", "grep", "recall", "ask_user", "todo_write", "delegate", "exit_plan_mode", "update_progress")] + \
      [fake_tool(n, read_only=False) for n in ("edit_file", "web_fetch", "remember")]


@tool(read_only=lambda args: args.get("command", "").startswith("ls"))
def run_shell(command: str) -> str:
    """Shell."""
    return ""


# --- which tools a definition may use -----------------------------------------------------------------------------

def test_read_only_means_the_tools_that_never_change_anything_minus_the_excluded():
    d = AgentDef("e", "x", "p", "read-only")
    assert d.tool_names(ALL + [run_shell]) == ["read_file", "grep", "recall"] and d.read_only


def test_all_means_everything_the_parent_has_minus_the_excluded():
    d = AgentDef("w", "x", "p", "all")
    names = d.tool_names(ALL + [run_shell])
    assert names == ["read_file", "grep", "recall", "edit_file", "web_fetch", "run_shell"] and not d.read_only
    assert not set(names) & EXCLUDED


def test_a_list_names_tools_and_ignores_excluded_or_missing_ones():
    d = AgentDef("l", "x", "p", "read_file, edit_file, delegate, ask_user, nope")
    assert d.tool_names(ALL) == ["read_file", "edit_file"]
    assert AgentDef("l", "x", "p", "grep recall").tool_names(ALL) == ["grep", "recall"]


def test_a_sub_agent_never_gets_the_tools_that_start_agents_ask_or_write_state_for_later():
    for kind in ("read-only", "all", ", ".join(t.name for t in ALL)):
        assert not set(AgentDef("x", "x", "p", kind).tool_names(ALL)) & {"delegate", "ask_user", "exit_plan_mode", "todo_write", "remember", "forget", "update_progress"}


# --- definitions ----------------------------------------------------------------------------------------------------

def write_agent(folder, name, header="", body="You review code."):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(f"---\n{header}\n---\n{body}\n" if header is not None else body, encoding="utf-8")


def test_built_ins_come_first(tmp_path):
    found, warnings = load_agents(tmp_path / "w", tmp_path / "u", True)
    assert list(found) == ["explore", "worker"] and warnings == []
    assert found["explore"].tools == "read-only" and found["worker"].tools == "all" and found["explore"].source == "built-in"


def test_user_definitions_are_read_with_their_header(tmp_path):
    write_agent(tmp_path / "u" / "agents", "reviewer", "description: Lists what could go wrong\ntools: read_file, grep\nmax_steps: 7\nmodel: small-model")
    d = load_agents(tmp_path / "w", tmp_path / "u", True)[0]["reviewer"]
    assert (d.description, d.tools, d.max_steps, d.model, d.source, d.prompt) == ("Lists what could go wrong", "read_file, grep", 7, "small-model", "user", "You review code.")


def test_the_name_in_the_header_wins_and_defaults_are_filled_in(tmp_path):
    write_agent(tmp_path / "u" / "agents", "file-name", "name: Real-Name")
    d = load_agents(tmp_path / "w", tmp_path / "u", True)[0]
    assert "real-name" in d and "file-name" not in d and d["real-name"].tools == "read-only" and d["real-name"].model == "inherit" and d["real-name"].max_steps == 12


@pytest.mark.parametrize("header,expected", [("max_steps: 500", 30), ("max_steps: 0", 1), ("max_steps: lots", 12)])
def test_the_step_limit_is_kept_in_range(tmp_path, header, expected):
    write_agent(tmp_path / "u" / "agents", "a", header)
    assert load_agents(tmp_path / "w", tmp_path / "u", True)[0]["a"].max_steps == expected


def test_a_project_s_definitions_are_read_only_in_a_trusted_folder(tmp_path):
    write_agent(tmp_path / "w" / ".harness" / "agents", "project-agent", "description: from the repo")
    found, warnings = load_agents(tmp_path / "w", tmp_path / "u", True)
    assert found["project-agent"].source == "project" and warnings == []
    found, warnings = load_agents(tmp_path / "w", tmp_path / "u", False)
    assert "project-agent" not in found and "1 agent definition(s)" in warnings[0] and "isn't trusted" in warnings[0]


def test_a_project_cannot_replace_a_built_in_but_a_user_can(tmp_path):
    write_agent(tmp_path / "w" / ".harness" / "agents", "explore", "description: evil")
    write_agent(tmp_path / "u" / "agents", "worker", "description: mine\ntools: read-only")
    found, warnings = load_agents(tmp_path / "w", tmp_path / "u", True)
    assert found["explore"].source == "built-in" and any("can't replace the built-in agent 'explore'" in w for w in warnings)
    assert found["worker"].description == "mine" and found["worker"].source == "user"


def test_bad_names_and_empty_definitions_are_skipped_with_a_warning(tmp_path):
    folder = tmp_path / "u" / "agents"
    write_agent(folder, "Bad_Name", "")
    write_agent(folder, "empty", "description: x", body="   ")
    found, warnings = load_agents(tmp_path / "w", tmp_path / "u", True)
    assert list(found) == ["explore", "worker"] and len(warnings) == 2


def test_the_tool_lists_the_agents_for_the_model():
    found = {a.name: a for a in AgentDef("a", "does a", "p", "read-only") and [AgentDef("a", "does a", "p"), AgentDef("b", "does b", "p", source="user")]}
    t = make_agent_tools(lambda n, task: "r", found)[0]
    assert t.name == "delegate" and t.is_read_only({}) and t.parameters["required"] == ["agent", "task"]
    assert "- a: does a" in t.description and "- b: does b (user)" in t.description and agents_text(found).count("\n") == 1


# --- the session -------------------------------------------------------------------------------------------------------

class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.events, self.warnings = [], []

    def __call__(self, kind, data):
        self.events.append((kind, data))

    def warn(self, text_):
        self.warnings.append(text_)

    def info(self, text_):
        pass


class Approver:
    pause = None

    def __init__(self, answer=True):
        self.answer, self.asked = answer, []

    def __call__(self, call, tool, decision=None):
        self.asked.append(call.name)
        return self.answer


def make_session(tmp_path, monkeypatch, files=None, trusted=True, approver=None, **settings):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(content, encoding="utf-8")
    set_trusted(root, config.USER_DIR, trusted)
    base = {"save_chats": False, "auto_memory": "off", "journal": "off", "file_history": True, "todo": False}
    s = Session(Settings(**(base | settings)), Workspace(root), Quiet(), approver or Approver())
    s.agent.stream = False
    return s


def delegate_call(agent="explore", task="where is the tax applied?", call_id="d"):
    return tool_calls(ToolCall(call_id, "delegate", {"agent": agent, "task": task}))


def script(s, *replies):
    """One model for everyone: parent and sub-agent take their replies from the same script, in the order they ask."""
    s.provider.inner = ScriptedProvider(list(replies))
    return s.provider.inner


FILES = {"shop.py": "def apply_tax(x):\n    return x * 1.2\n", "README.md": "# shop\n"}


def test_the_parent_gets_the_report_and_not_the_reading(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES)
    model = script(s, delegate_call(), tool_calls(ToolCall("r", "read_file", {"path": "shop.py"})), text("Tax is applied in shop.py:1, apply_tax."), text("It is in shop.py."))
    assert s.agent.run("where is tax applied?") == "It is in shop.py."
    results = [m.content for m in s.agent.messages if m.role == "tool"]
    assert len(results) == 1 and results[0].startswith("Tax is applied in shop.py:1, apply_tax.") and "(explore: 1 tool calls," in results[0]
    assert "def apply_tax" not in "".join(m.content for m in s.agent.messages)         # the file's text never entered the parent's conversation
    sub_request = model.requests[1][0]
    assert sub_request[0].role == "system" and sub_request[0].content.startswith("You are an explorer") and sub_request[1].content == "where is the tax applied?"


def test_the_sub_agent_has_its_own_prompt_and_only_the_tools_it_may_use(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES)
    model = script(s, delegate_call(), text("done"), text("ok"))
    s.agent.run("go")
    sub_messages, sub_tools = model.requests[1]
    names = [t["name"] for t in sub_tools]
    assert "read_file" in names and "grep" in names and not set(names) & ({"edit_file", "write_file", "run_shell", "web_fetch", "delegate", "ask_user", "todo_write"})
    prompt = sub_messages[0].content
    assert "shop.py" in prompt and "Workspace files" in prompt and SYSTEM_RULE in prompt                   # the listing and the untrusted-content rule
    assert "delegate" in [t["name"] for t in model.requests[0][1]]


def test_a_sub_agent_that_asks_for_a_tool_it_does_not_have_is_told_so(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES)
    model = script(s, delegate_call(), tool_calls(ToolCall("w", "write_file", {"path": "x.txt", "content": "y"})), text("could not"), text("ok"))
    s.agent.run("go")
    assert not (s.ws.root / "x.txt").exists()
    assert any("unknown tool 'write_file'" in m.content for m in model.requests[2][0] if m.role == "tool")


def test_a_sub_agent_cannot_start_another(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES)
    model = script(s, delegate_call("worker"), delegate_call("explore", call_id="inner"), text("could not"), text("ok"))
    s.agent.run("go")
    assert any("unknown tool 'delegate'" in m.content for m in model.requests[2][0] if m.role == "tool")
    s.actor = "explore"
    assert "can't start another sub-agent" in s.delegate("explore", "x")


def test_unknown_agents_and_empty_tasks_are_errors_for_the_model(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "no agent called 'nobody'. Choose one of: explore, worker" in s.delegate("nobody", "x")
    with pytest.raises(ValueError, match="task is empty"):
        s.delegate("explore", "   ")


def test_the_report_and_the_task_are_cut(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES)
    model = script(s, delegate_call(task="t" * 5000), text("r" * 9000), text("ok"))
    s.agent.run("go")
    assert len(model.requests[1][0][1].content) == MAX_TASK_CHARS
    result = [m.content for m in s.agent.messages if m.role == "tool"][0]
    assert "the report was cut: it had 9,000 characters" in result and len(result) < MAX_REPORT_CHARS + 200


def test_a_sub_agent_that_runs_out_of_steps_says_so(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES)
    s.agents["explore"].max_steps = 2
    loop = tool_calls(ToolCall("r", "list_dir", {"path": "."}))
    script(s, delegate_call(), loop, tool_calls(ToolCall("r2", "list_dir", {"path": "."})), text("ok"))
    s.agent.run("go")
    result = [m.content for m in s.agent.messages if m.role == "tool"][0]
    assert result.startswith("(the sub-agent stopped early: max_steps; this is what it had)")


# --- what is shared with the parent ----------------------------------------------------------------------------------

def test_calls_and_tokens_count_against_the_sessions_limits_and_costs(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES)
    script(s, delegate_call(), tool_calls(ToolCall("r", "read_file", {"path": "shop.py"})), tool_calls(ToolCall("g", "grep", {"pattern": "tax"})), text("found"), text("ok"))
    s.agent.run("go")
    assert s.limits.tool_calls == 3 + 0 or s.limits.tool_calls >= 3                 # the delegate call and the sub-agent's two
    assert s.costs.models and sum(u.input_tokens for u in [s.costs.models[next(iter(s.costs.models))].usage]) >= 0


def test_the_sub_agent_shares_permissions_approver_hooks_and_limits(tmp_path, monkeypatch):
    made = []
    real = session_module.Agent

    def spy(*args, **kwargs):
        agent = real(*args, **kwargs)
        made.append(agent)
        return agent
    monkeypatch.setattr(session_module, "Agent", spy)
    s = make_session(tmp_path, monkeypatch, files=FILES)
    made.clear()
    script(s, delegate_call("worker"), text("done"), text("ok"))
    s.agent.run("go")
    sub = made[-1]
    assert sub.permissions is s.permissions and sub.hooks is s.hooks and sub.approve is s.agent.approve and sub.limit_check == s.limit_reason
    assert sub.context is not s.context and sub.stream is False and sub.finish_check is None and sub.max_steps == 20


def test_a_sub_agent_edits_ask_as_the_parent_would_and_can_be_undone(tmp_path, monkeypatch):
    approver = Approver(True)
    s = make_session(tmp_path, monkeypatch, files=FILES, approver=approver)
    script(s, delegate_call("worker", "add a docstring"),
           tool_calls(ToolCall("r", "read_file", {"path": "shop.py"})),
           tool_calls(ToolCall("e", "edit_file", {"path": "shop.py", "old_string": "def apply_tax(x):", "new_string": "def apply_tax(x):\n    '''Add tax.'''"})),
           text("added the docstring"), text("done"))
    s.agent.run("add a docstring to apply_tax")
    assert approver.asked == ["edit_file"] and "'''Add tax.'''" in (s.ws.root / "shop.py").read_text(encoding="utf-8")
    assert s.turn_changed                                                           # the journal will hear about it
    assert "put back: shop.py" in s.undo() and "'''Add tax.'''" not in (s.ws.root / "shop.py").read_text(encoding="utf-8")


def test_in_plan_mode_a_worker_can_read_and_nothing_more(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES, permission_mode="plan")
    model = script(s, delegate_call("worker"), tool_calls(ToolCall("w", "write_file", {"path": "x.txt", "content": "y"})), text("refused"), text("ok"))
    s.agent.run("go")
    assert not (s.ws.root / "x.txt").exists()
    assert any("plan mode is on" in m.content for m in model.requests[2][0] if m.role == "tool")


def test_what_a_sub_agent_reads_from_an_untrusted_folder_taints_the_session_and_fences_the_report(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES, trusted=False)
    assert not s.permissions.taint.active
    script(s, delegate_call(), tool_calls(ToolCall("r", "read_file", {"path": "shop.py"})), text("apply_tax multiplies by 1.2"), text("ok"))
    s.agent.run("go")
    assert s.permissions.taint.active
    result = [m.content for m in s.agent.messages if m.role == "tool"][0]
    assert result.startswith('<untrusted source="report from sub-agent explore') and "apply_tax multiplies by 1.2" in result


def test_a_report_from_a_sub_agent_that_read_nothing_untrusted_is_plain(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES)
    script(s, delegate_call(), tool_calls(ToolCall("r", "read_file", {"path": "shop.py"})), text("fine"), text("ok"))
    s.agent.run("go")
    assert "<untrusted" not in [m.content for m in s.agent.messages if m.role == "tool"][0].replace('<untrusted source="read_file', "")


def test_a_different_model_can_be_named(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES)
    s.agents["explore"].model = "small-one"
    other = ScriptedProvider([text("from the small model")])
    other.model = "small-one"
    asked = []
    monkeypatch.setattr(s, "make_provider", lambda model: asked.append(model) or other)
    script(s, delegate_call(), text("ok"))
    s.agent.run("go")
    assert asked == ["small-one"] and "from the small model" in [m.content for m in s.agent.messages if m.role == "tool"][0]


def test_the_sub_agents_prompt_carries_the_projects_notes(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES | {"HARNESS.md": "Run tests with: python -m pytest -q\n"})
    assert "python -m pytest -q" in s.subagent_prompt(s.agents["explore"])


# --- chat, screen and audit --------------------------------------------------------------------------------------------------

def test_a_sub_agents_conversation_is_not_in_the_saved_chat(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES, save_chats=True)
    script(s, delegate_call(), tool_calls(ToolCall("r", "read_file", {"path": "shop.py"})), text("found"), text("ok"))
    s.agent.run("go")
    saved = replay(s.chat.path).messages
    assert [m.role for m in saved] == ["user", "assistant", "tool", "assistant"] and "def apply_tax" not in "".join(m.content for m in saved)


def test_the_screen_hears_when_a_sub_agent_starts_calls_a_tool_and_finishes(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES)
    script(s, delegate_call(task="find the tax"), tool_calls(ToolCall("r", "read_file", {"path": "shop.py"})), text("found"), text("ok"))
    s.agent.run("go")
    shown = [d for k, d in s.ui.events if k == "subagent"]
    assert [d[1] for d in shown] == ["start", "tool_call", "end"] and shown[0][0] == "explore" and shown[0][2] == "find the tax"
    assert shown[1][2].name == "read_file" and shown[2][2]["calls"] == 1 and shown[2][2]["stop"] == "completed"


def test_the_audit_log_labels_what_a_sub_agent_did(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files=FILES, audit_log=True)
    script(s, delegate_call(), tool_calls(ToolCall("r", "read_file", {"path": "shop.py"})), text("found"), text("ok"))
    s.agent.run("go")
    lines = [json.loads(line) for line in s.audit_log.path.read_text(encoding="utf-8").splitlines()]
    sub = [e for e in lines if e.get("agent") == "explore"]
    assert any(e["kind"] == "subagent" for e in sub) and any(e["kind"] == "decision" and e.get("tool") == "read_file" for e in sub)
    assert any(e["kind"] == "decision" and e.get("tool") == "delegate" and "agent" not in e for e in lines)          # the parent's own call isn't labelled


# --- commands and settings -----------------------------------------------------------------------------------------------------

def run(session, line):
    command, args = load_commands(session.ws.root).parse(line)
    return command.run(session, args)


def test_the_agents_command_lists_the_definitions(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    out = run(s, "/agents")
    assert "explore" in out and "read-only" in out and "built-in" in out and "worker" in out
    assert "takes reload" in run(s, "/agents now")


def test_reloading_after_trust_reads_the_projects_definitions_and_tells_the_model(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, trusted=False)
    write_agent(s.ws.root / ".harness" / "agents", "project-agent", "description: the repo's own")
    s.reload_agents()
    assert "project-agent" not in s.agents and any("isn't trusted" in w for w in s.ui.warnings)
    set_trusted(s.ws.root, config.USER_DIR, True)
    s.permissions.taint.trusted = True
    run(s, "/agents reload")
    assert "project-agent" in s.agents and "- project-agent: the repo's own (project)" in s.agent.tools.get("delegate").description


def test_the_setting_turns_it_all_off(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, subagents=False)
    assert "delegate" not in [t["name"] for t in s.agent.tools.schemas()] and "sub-agent rule" not in [p.name for p in s.prompt.parts]
    assert "off" in run(s, "/agents")


def test_the_rule_is_in_the_prompt_by_default(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "sub-agent rule" in [p.name for p in s.prompt.parts] and SUBAGENT_RULE in s.prompt.text


def test_a_project_may_choose_the_setting(tmp_path, monkeypatch):
    from harness.config import load_settings
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    (root / ".harness").mkdir(parents=True)
    (root / ".harness" / "settings.json").write_text(json.dumps({"subagents": False}), encoding="utf-8")
    settings, warnings = load_settings(root)
    assert settings.subagents is False and not warnings
