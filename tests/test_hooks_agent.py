"""Lesson 33: hooks inside the agent loop, the settings and the session."""
import json
import sys

import pytest

from harness import config
from harness.agent import Agent
from harness.commands import load_commands
from harness.config import ConfigError, Settings, load_settings
from harness.hooks import Hooks, check_hooks, collect
from harness.messages import ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.security.permissions import Permissions, Rule
from harness.session import Session
from harness.tools import default_tools
from harness.tui.plain import PlainApprover, PlainUI
from harness.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    return Workspace(tmp_path)


def hook_cmd(tmp_path, body, name="hook.py"):
    path = tmp_path / name
    path.write_text("import json, sys\npayload = json.load(sys.stdin)\n" + body, encoding="utf-8")
    return f'"{sys.executable}" "{path}"'


def hooks_for(ws, perms, *entries):
    grouped: dict = {}
    for event, entry in entries:
        grouped.setdefault(event, []).append(entry)
    check_hooks(grouped, "test")
    return Hooks(collect([("user", grouped)]), ws.root, perms)


def run(ws, perms, hooks, replies, approve=None, user="go"):
    provider = ScriptedProvider(replies)
    events = []
    agent = Agent(provider, default_tools(ws), "s", approve=approve, stream=False, permissions=perms, hooks=hooks,
                  on_event=lambda k, d: events.append((k, d)))
    answer = agent.run(user)
    return provider, agent, events, answer


def asks(log):
    def approve(call, tool, decision):
        log.append((call.name, decision.reason, list(decision.notes)))
        return True
    return approve


def write(path="src/a.py", content="x", id="1"):
    return tool_calls(ToolCall(id, "write_file", {"path": path, "content": content}))


# --- pre_tool_use --------------------------------------------------------------------------

def test_a_hook_can_refuse_a_call_the_mode_would_allow(ws, tmp_path):
    perms = Permissions(ws, "bypass")
    hooks = hooks_for(ws, perms, ("pre_tool_use", {"command": hook_cmd(tmp_path, "print(json.dumps({'decision': 'deny', 'reason': 'not today'}))\n"),
                                                    "match": "write_file(src/**)"}))
    provider, _, events, _ = run(ws, perms, hooks, [write(), text("done")])
    assert not (ws.root / "src" / "a.py").exists()
    result = [m.content for m in provider.requests[-1][0] if m.role == "tool"][0]
    assert result.startswith("Error: a hook refused it: not today. Do what that says;") and "tell the user" in result
    assert [k for k, _ in events if k in ("hook", "tool_refused")] == ["hook", "tool_refused"]


def test_a_hook_can_make_an_allowed_call_ask(ws, tmp_path):
    perms = Permissions(ws, "bypass")
    hooks = hooks_for(ws, perms, ("pre_tool_use", {"command": hook_cmd(tmp_path, "print(json.dumps({'decision': 'ask', 'reason': 'migration', 'context': 'check the ticket'}))\n")}))
    log = []
    run(ws, perms, hooks, [write(), text("done")], approve=asks(log))
    assert log == [("write_file", "a hook asks first: migration", ["hook: check the ticket"])]


def test_a_hook_that_asks_where_something_already_asks_changes_only_the_reason(ws, tmp_path):
    perms = Permissions(ws)
    hooks = hooks_for(ws, perms, ("pre_tool_use", {"command": hook_cmd(tmp_path, "print(json.dumps({'decision': 'ask', 'reason': 'be careful'}))\n")}))
    log = []
    run(ws, perms, hooks, [write(), text("done")], approve=asks(log))
    assert [r for _, r, _ in log] == ["a hook asks first: be careful"]


def test_a_hooks_allow_settles_a_routine_question(ws, tmp_path):
    perms = Permissions(ws)
    hooks = hooks_for(ws, perms, ("pre_tool_use", {"command": hook_cmd(tmp_path, "print(json.dumps({'decision': 'allow'}))\n"),
                                                    "match": "write_file(src/**)"}))
    log = []
    run(ws, perms, hooks, [write(), text("done")], approve=asks(log))
    assert log == [] and (ws.root / "src" / "a.py").exists()


@pytest.mark.parametrize("setup, path", [
    ("protected", ".git/hooks/pre-commit"),
    ("ask rule", "src/a.py"),
    ("tainted", "src/a.py"),
])
def test_a_hooks_allow_cannot_override_what_must_ask(ws, tmp_path, setup, path):
    perms = Permissions(ws)
    if setup == "ask rule":
        perms.rules.append(Rule.parse("write_file(src/**)", "ask", "user"))
    if setup == "tainted":
        perms.taint.add("web", "web_fetch https://x.example/")
    hooks = hooks_for(ws, perms, ("pre_tool_use", {"command": hook_cmd(tmp_path, "print(json.dumps({'decision': 'allow'}))\n")}))
    log = []
    run(ws, perms, hooks, [write(path), text("done")], approve=lambda c, t, decision=None: log.append(decision.reason) or False)
    assert len(log) == 1 and not (ws.root / path).exists()


def test_a_hooks_allow_cannot_override_a_deny_rule_or_plan_mode(ws, tmp_path):
    allow = hook_cmd(tmp_path, "print(json.dumps({'decision': 'allow'}))\n")
    for setup in ("deny rule", "plan"):
        perms = Permissions(ws, "plan" if setup == "plan" else "default")
        if setup == "deny rule":
            perms.rules.append(Rule.parse("write_file(src/**)", "deny", "user"))
        hooks = hooks_for(ws, perms, ("pre_tool_use", {"command": allow}))
        run(ws, perms, hooks, [write(), text("done")])
        assert not (ws.root / "src" / "a.py").exists(), setup


def test_a_failing_hook_never_allows(ws, tmp_path):
    perms = Permissions(ws, "bypass")
    hooks = hooks_for(ws, perms, ("pre_tool_use", {"command": hook_cmd(tmp_path, "sys.exit(7)\n")}))
    log = []
    run(ws, perms, hooks, [write(), text("done")], approve=asks(log))
    assert len(log) == 1 and "a hook failed, so it can't confirm this call" in log[0][1]
    assert any("a hook failed: " in n and "exit code 7" in n for n in log[0][2])


def test_with_nobody_to_ask_a_failing_hook_means_the_call_does_not_run(ws, tmp_path):
    perms = Permissions(ws, "bypass")
    hooks = hooks_for(ws, perms, ("pre_tool_use", {"command": hook_cmd(tmp_path, "print('not json')\n")}))
    run(ws, perms, hooks, [write(), text("done")])
    assert not (ws.root / "src" / "a.py").exists()


def test_hooks_see_the_state_of_the_chat(ws, tmp_path):
    seen = tmp_path / "seen.json"
    perms = Permissions(ws, "bypass")
    perms.taint.add("file", "read_file README.md")
    hooks = hooks_for(ws, perms, ("pre_tool_use", {"command": hook_cmd(tmp_path, f"open({str(seen)!r}, 'w').write(json.dumps(payload))\n")}))
    run(ws, perms, hooks, [write(), text("done")], approve=lambda c, t, decision=None: False)
    payload = json.loads(seen.read_text(encoding="utf-8"))
    assert payload["mode"] == "bypass" and payload["tainted"] is True


def test_hooks_that_match_nothing_cost_nothing(ws, tmp_path):
    marker = tmp_path / "ran.txt"
    perms = Permissions(ws, "bypass")
    hooks = hooks_for(ws, perms, ("pre_tool_use", {"command": hook_cmd(tmp_path, f"open({str(marker)!r}, 'w').write('x')\n"), "match": "run_shell(git push*)"}))
    run(ws, perms, hooks, [write(), text("done")])
    assert not marker.exists() and (ws.root / "src" / "a.py").exists()


# --- post_tool_use -------------------------------------------------------------------------

def test_post_hooks_add_context_after_the_fenced_result(ws, tmp_path):
    (ws.root / "src" / "a.py").write_text("print('hi')\n", encoding="utf-8")
    cmd = hook_cmd(tmp_path, "print(json.dumps({'context': 'lint: 0 problems (' + payload['tool'] + ')'}))\n")
    perms = Permissions(ws)
    hooks = hooks_for(ws, perms, ("post_tool_use", {"command": cmd, "match": "read_file"}))
    provider = ScriptedProvider([tool_calls(ToolCall("1", "read_file", {"path": "src/a.py"})), text("done")])
    events = []
    Agent(provider, default_tools(ws), "s", stream=False, permissions=perms, hooks=hooks, fence_untrusted=True,
          on_event=lambda k, d: events.append((k, d))).run("go")
    seen = [m.content for m in provider.requests[-1][0] if m.role == "tool"][0]
    assert seen.startswith("<untrusted") and seen.endswith("</untrusted>\n\n[hook] lint: 0 problems (read_file)")   # the hook's words aren't fenced
    shown = next(d for k, d in events if k == "tool_result")[1]
    assert "<untrusted" not in shown and shown.endswith("[hook] lint: 0 problems (read_file)")


def test_post_hooks_run_only_for_calls_that_ran(ws, tmp_path):
    marker = tmp_path / "ran.txt"
    cmd = hook_cmd(tmp_path, f"open({str(marker)!r}, 'a').write('x')\n")
    perms = Permissions(ws, "plan")
    hooks = hooks_for(ws, perms, ("post_tool_use", {"command": cmd}))
    run(ws, perms, hooks, [write(), text("done")])          # refused in plan mode: nothing ran
    assert not marker.exists()


# --- user_prompt_submit --------------------------------------------------------------------

def test_a_prompt_hook_can_block_the_message_before_the_model_sees_it(ws, tmp_path):
    cmd = hook_cmd(tmp_path, "print(json.dumps({'decision': 'deny', 'reason': 'no passwords in prompts'}) if 'password' in payload['prompt'] else '')\n")
    perms = Permissions(ws)
    hooks = hooks_for(ws, perms, ("user_prompt_submit", {"command": cmd}))
    provider, agent, events, answer = run(ws, perms, hooks, [text("hello")], user="my password is hunter2")
    assert answer == "(blocked by a hook: no passwords in prompts)" and agent.stop_reason == "blocked"
    assert provider.requests == [] and len(agent.messages) == 1          # the model was never called; nothing was kept
    provider, agent, events, answer = run(ws, perms, hooks, [text("hello")], user="hi there")
    assert answer == "hello" and agent.stop_reason == "completed"


def test_a_prompt_hook_can_add_context(ws, tmp_path):
    cmd = hook_cmd(tmp_path, "print(json.dumps({'context': 'current branch: main'}))\n")
    perms = Permissions(ws)
    hooks = hooks_for(ws, perms, ("user_prompt_submit", {"command": cmd}))
    provider, agent, _, _ = run(ws, perms, hooks, [text("ok")], user="what branch?")
    sent = [m.content for m in provider.requests[0][0] if m.role == "user"][0]
    assert sent == "what branch?\n\n[from a hook]\ncurrent branch: main"


# --- settings and the session --------------------------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch):
    user = tmp_path / "home"
    monkeypatch.setattr(config, "USER_DIR", user)
    return user


def write_settings(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_hooks_from_every_layer_add_up_and_keep_their_source(home, tmp_path):
    project = tmp_path / "project"
    write_settings(home / "settings.json", {"hooks": {"pre_tool_use": [{"command": "a"}]}})
    write_settings(project / ".harness" / "settings.json", {"hooks": {"post_tool_use": [{"command": "b", "match": "edit_file"}]}})
    write_settings(project / ".harness" / "settings.local.json", {"hooks": {"pre_tool_use": [{"command": "c", "timeout": 5}]}})
    settings, warnings = load_settings(project, environ={"HARNESS_HOOKS": json.dumps({"user_prompt_submit": [{"command": "d"}]})})
    assert warnings == []
    assert [(h["event"], h["command"], h["match"], h["timeout"], h["source"]) for h in settings.hooks] == [
        ("pre_tool_use", "a", None, 10, "user"), ("post_tool_use", "b", "edit_file", 10, "project"),
        ("pre_tool_use", "c", None, 5, "local"), ("user_prompt_submit", "d", None, 10, "environment")]


def test_a_bad_hooks_setting_is_an_error_naming_the_file(home, tmp_path):
    write_settings(home / "settings.json", {"hooks": {"pre_tool": [{"command": "a"}]}})
    with pytest.raises(ConfigError, match=r"settings.json|user.*unknown hook event 'pre_tool'"):
        load_settings(tmp_path, environ={})


class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.warnings = []

    def warn(self, text):
        self.warnings.append(text)


def make_session(ws, entries):
    return Session(Settings(hooks=entries), ws, Quiet(), PlainApprover())


ENTRIES = [{"event": "pre_tool_use", "command": "user-hook", "match": None, "timeout": 10, "source": "user"},
           {"event": "pre_tool_use", "command": "project-hook", "match": None, "timeout": 10, "source": "project"}]


def test_project_hooks_do_not_run_in_a_folder_that_is_not_trusted(home, ws):
    session = make_session(ws, ENTRIES)
    assert [h.command for h in session.hooks.hooks] == ["user-hook"]
    assert any("1 hook(s) from this project's settings were not run" in w for w in session.ui.warnings)


def test_trusting_the_folder_turns_project_hooks_on_and_untrusting_turns_them_off(home, ws):
    session = make_session(ws, ENTRIES)
    command = lambda line: load_commands(ws.root).parse(line)[0].run(session, "")   # noqa: E731
    command("/trust")
    assert [h.command for h in session.hooks.hooks] == ["user-hook", "project-hook"]
    command("/untrust")
    assert [h.command for h in session.hooks.hooks] == ["user-hook"]


def test_a_trusted_folder_starts_with_all_hooks_and_no_warning(home, ws):
    from harness.security.trust import set_trusted
    set_trusted(ws.root, home, True)
    session = make_session(ws, ENTRIES)
    assert len(session.hooks.hooks) == 2 and session.ui.warnings == []
    assert session.agent.hooks is session.hooks


def test_the_hooks_command_lists_each_hook_and_whether_it_runs(home, ws):
    session = make_session(ws, ENTRIES)
    out = load_commands(ws.root).parse("/hooks")[0].run(session, "")
    assert "runs     pre_tool_use: user-hook (user)" in out and "not run  pre_tool_use: project-hook (project)" in out
    assert "no hooks" in load_commands(ws.root).parse("/hooks")[0].run(make_session(ws, []), "")


def test_show_config_lists_hooks_with_their_layer():
    settings = Settings(hooks=ENTRIES[:1] + [{"event": "pre_tool_use", "command": "x", "match": "write_file", "timeout": 10, "source": "local"}])
    text_ = config.describe(settings)
    assert "pre_tool_use" in text_ and "write_file" in text_ and "(local)" in text_
