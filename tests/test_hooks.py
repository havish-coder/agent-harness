"""Lesson 33: hooks run the user's scripts at fixed points; they may tighten decisions, never loosen the
protected ones, and a hook that fails never allows."""
import json
import os
import sys

import pytest

from harness.hooks import HookError, Hooks, check_hooks, collect
from harness.messages import ToolCall
from harness.security.permissions import Permissions
from harness.tools import default_tools
from harness.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path)


@pytest.fixture
def tools(ws):
    return {t.name: t for t in default_tools(ws)}


def script(tmp_path, body: str, name="hook.py") -> str:
    """A hook command: our Python running a script. The script reads the JSON payload from stdin."""
    path = tmp_path / name
    path.write_text("import json, sys\npayload = json.load(sys.stdin)\n" + body, encoding="utf-8")
    return f'"{sys.executable}" "{path}"'


def layers(*entries, source="user"):
    """Hooks for [(event, entry), ...]."""
    grouped: dict = {}
    for event, entry in entries:
        grouped.setdefault(event, []).append(entry)
    check_hooks(grouped, "test")
    return collect([(source, grouped)])


def make(ws, hooks):
    return Hooks(hooks, ws.root, Permissions(ws))


def call(name, **arguments):
    return ToolCall("1", name, arguments)


# --- settings ------------------------------------------------------------------------------

def test_hooks_are_collected_with_their_source_and_match():
    hooks = layers(("pre_tool_use", {"command": "a.py", "match": "run_shell(git push*)", "timeout": 5}),
                   ("post_tool_use", {"command": "b.py"}), source="local")
    assert [(h.event, h.command, str(h.match), h.timeout, h.source) for h in hooks] == [
        ("pre_tool_use", "a.py", "run_shell(git push*)", 5.0, "local"), ("post_tool_use", "b.py", "None", 10.0, "local")]
    assert "pre_tool_use for run_shell(git push*): a.py (local)" in str(hooks[0])


@pytest.mark.parametrize("value, message", [
    ([], "must be an object"),
    ({"pre_tool": []}, "unknown hook event 'pre_tool'; choose from"),
    ({"pre_tool_use": {}}, "must be a list"),
    ({"pre_tool_use": ["x"]}, 'needs a "command" string'),
    ({"pre_tool_use": [{"command": " "}]}, 'needs a "command" string'),
    ({"pre_tool_use": [{"command": "x", "matcher": "y"}]}, "unknown key"),
    ({"pre_tool_use": [{"command": "x", "timeout": 0}]}, "number of seconds"),
    ({"pre_tool_use": [{"command": "x", "timeout": 600}]}, "number of seconds"),
    ({"pre_tool_use": [{"command": "x", "timeout": True}]}, "number of seconds"),
    ({"pre_tool_use": [{"command": "x", "match": "not a rule("}]}, "can't read the rule"),
    ({"user_prompt_submit": [{"command": "x", "match": "run_shell"}]}, "only applies to"),
])
def test_bad_hook_settings_are_errors(value, message):
    with pytest.raises(HookError, match=message):
        check_hooks(value, "settings.json")


# --- running one hook ----------------------------------------------------------------------

def test_the_hook_gets_the_call_as_json(ws, tools, tmp_path):
    seen = tmp_path / "seen.json"
    cmd = script(tmp_path, f"open({str(seen)!r}, 'w').write(json.dumps(payload))\n")
    hooks = make(ws, layers(("pre_tool_use", {"command": cmd})))
    assert hooks.pre_tool(call("run_shell", command="ls -l"), tools["run_shell"]).decision is None
    payload = json.loads(seen.read_text(encoding="utf-8"))
    assert payload["event"] == "pre_tool_use" and payload["tool"] == "run_shell"
    assert payload["arguments"] == {"command": "ls -l"} and payload["subject"] == "ls -l"
    assert payload["mode"] == "default" and payload["tainted"] is False and payload["cwd"] == str(ws.root)


def test_a_hook_runs_in_the_workspace_with_its_event_in_the_environment(ws, tools, tmp_path):
    cmd = script(tmp_path, "import os\nprint(json.dumps({'decision': 'ask', 'reason': os.getcwd() + '|' + os.environ['HARNESS_HOOK_EVENT']}))\n")
    result = make(ws, layers(("pre_tool_use", {"command": cmd}))).pre_tool(call("write_file", path="a", content="x"), tools["write_file"])
    assert result.decision == "ask" and result.reason == f"{ws.root}|pre_tool_use"


@pytest.mark.parametrize("body, decision, reason", [
    ("print(json.dumps({'decision': 'deny', 'reason': 'no pushes'}))", "deny", "no pushes"),
    ("print(json.dumps({'decision': 'ask'}))", "ask", ""),
    ("print(json.dumps({'decision': 'allow', 'reason': 'fine'}))", "allow", "fine"),
    ("sys.stderr.write('not on fridays\\n'); sys.exit(2)", "deny", "not on fridays"),
    ("sys.exit(2)", "deny", "the hook refused it (exit code 2)"),
    ("pass", None, ""),
    ("print(json.dumps({'context': 'note'}))", None, ""),
])
def test_what_a_hook_can_answer(ws, tools, tmp_path, body, decision, reason):
    result = make(ws, layers(("pre_tool_use", {"command": script(tmp_path, body + "\n")}))).pre_tool(
        call("run_shell", command="git push"), tools["run_shell"])
    assert (result.decision, result.reason, result.failed) == (decision, reason, None)


@pytest.mark.parametrize("body, why", [
    ("sys.exit(1)", "exit code 1"),
    ("sys.stderr.write('boom\\n'); sys.exit(3)", "exit code 3: boom"),
    ("print('not json')", "isn't JSON"),
    ("print(json.dumps({'decision': 'maybe'}))", "must be allow, ask or deny"),
    ("print(json.dumps([1]))", "must be allow, ask or deny"),
    ("raise RuntimeError('bug in the hook')", "exit code 1: RuntimeError: bug in the hook"),
])
def test_a_hook_that_cant_answer_is_a_failure_not_an_answer(ws, tools, tmp_path, body, why):
    result = make(ws, layers(("pre_tool_use", {"command": script(tmp_path, body + "\n")}))).pre_tool(
        call("run_shell", command="ls"), tools["run_shell"])
    assert result.decision is None and why in result.failed


def test_a_slow_hook_is_stopped(ws, tools, tmp_path):
    cmd = script(tmp_path, "import time\ntime.sleep(30)\n")
    result = make(ws, layers(("pre_tool_use", {"command": cmd, "timeout": 1}))).pre_tool(call("run_shell", command="ls"), tools["run_shell"])
    assert "timed out after 1 s" in result.failed


def test_a_hook_that_does_not_exist_is_a_failure(ws, tools):
    result = make(ws, layers(("pre_tool_use", {"command": "definitely-not-a-program-xyz"}))).pre_tool(
        call("run_shell", command="ls"), tools["run_shell"])
    assert result.failed and result.decision is None


def test_hooks_get_no_secrets(ws, tools, tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_API_KEY", "sk-lab-0123456789abcdefghijklmnop")
    cmd = script(tmp_path, "import os\nprint(json.dumps({'decision': 'ask', 'reason': str(os.environ.get('LAB_API_KEY'))}))\n")
    assert make(ws, layers(("pre_tool_use", {"command": cmd}))).pre_tool(call("run_shell", command="ls"), tools["run_shell"]).reason == "None"
    kept = Hooks(layers(("pre_tool_use", {"command": cmd})), ws.root, Permissions(ws), env_keep=["LAB_API_KEY"])
    assert kept.pre_tool(call("run_shell", command="ls"), tools["run_shell"]).reason.startswith("sk-lab")


# --- which calls a hook sees ---------------------------------------------------------------

def test_match_rules_pick_the_calls(ws, tools, tmp_path):
    cmd = script(tmp_path, "print(json.dumps({'decision': 'deny', 'reason': 'matched'}))\n")
    hooks = make(ws, layers(("pre_tool_use", {"command": cmd, "match": "run_shell(git push*)"})))
    deny = lambda command: hooks.pre_tool(call("run_shell", command=command), tools["run_shell"]).decision   # noqa: E731
    assert deny("git push origin main") == "deny"
    assert deny("echo hi && git push") == "deny" and deny("sudo git push") == "deny"      # like a deny rule: any command in it
    assert deny("git status") is None
    assert hooks.pre_tool(call("write_file", path="a", content="x"), tools["write_file"]).decision is None


def test_a_match_on_a_path_and_on_a_tool(ws, tools, tmp_path):
    cmd = script(tmp_path, "print(json.dumps({'decision': 'ask', 'reason': 'config'}))\n")
    hooks = make(ws, layers(("pre_tool_use", {"command": cmd, "match": "write_file(config/**)"}),
                            ("pre_tool_use", {"command": cmd, "match": "edit_file"})))
    assert hooks.pre_tool(call("write_file", path="config/app.toml", content="x"), tools["write_file"]).decision == "ask"
    assert hooks.pre_tool(call("write_file", path="src/app.py", content="x"), tools["write_file"]).decision is None
    assert hooks.pre_tool(call("edit_file", path="src/app.py", old_string="a", new_string="b"), tools["edit_file"]).decision == "ask"


def test_without_a_match_every_call_is_seen(ws, tools, tmp_path):
    cmd = script(tmp_path, "print(json.dumps({'decision': 'ask'}))\n")
    hooks = make(ws, layers(("pre_tool_use", {"command": cmd})))
    assert hooks.pre_tool(call("read_file", path="a"), tools["read_file"]).decision == "ask"


def test_events_are_kept_apart(ws, tools, tmp_path):
    cmd = script(tmp_path, "print(json.dumps({'decision': 'deny'}))\n")
    hooks = make(ws, layers(("post_tool_use", {"command": cmd})))
    assert hooks.pre_tool(call("run_shell", command="ls"), tools["run_shell"]).decision is None
    assert hooks.user_prompt("hello").decision is None


# --- several hooks -------------------------------------------------------------------------

def test_the_strictest_answer_wins_and_failures_are_kept(ws, tools, tmp_path):
    allow = script(tmp_path, "print(json.dumps({'decision': 'allow', 'context': 'one'}))\n", "a.py")
    ask = script(tmp_path, "print(json.dumps({'decision': 'ask', 'reason': 'check', 'context': 'two'}))\n", "b.py")
    deny = script(tmp_path, "print(json.dumps({'decision': 'deny', 'reason': 'stop'}))\n", "c.py")
    broken = script(tmp_path, "sys.exit(9)\n", "d.py")
    call_ = call("run_shell", command="ls")
    one = make(ws, layers(("pre_tool_use", {"command": allow}), ("pre_tool_use", {"command": ask}))).pre_tool(call_, tools["run_shell"])
    assert (one.decision, one.reason, one.context) == ("ask", "check", "one\ntwo")
    two = make(ws, layers(("pre_tool_use", {"command": ask}), ("pre_tool_use", {"command": deny}))).pre_tool(call_, tools["run_shell"])
    assert (two.decision, two.reason) == ("deny", "stop")
    three = make(ws, layers(("pre_tool_use", {"command": allow}), ("pre_tool_use", {"command": broken}))).pre_tool(call_, tools["run_shell"])
    assert three.decision == "allow" and "exit code 9" in three.failed


# --- post_tool_use and user_prompt_submit --------------------------------------------------

def test_post_tool_hooks_get_the_result_and_can_add_context(ws, tools, tmp_path):
    cmd = script(tmp_path, "print(json.dumps({'context': 'lint: ' + payload['result'][:5]}))\n")
    hooks = make(ws, layers(("post_tool_use", {"command": cmd, "match": "write_file"})))
    out = hooks.post_tool(call("write_file", path="a.py", content="x"), tools["write_file"], "wrote a.py (1 line)")
    assert out.context == "lint: wrote" and out.decision is None
    assert not hooks.post_tool(call("run_shell", command="ls"), tools["run_shell"], "x").context


def test_prompt_hooks_can_block_or_add_context(ws, tmp_path):
    block = script(tmp_path, "print(json.dumps({'decision': 'deny', 'reason': 'no secrets in prompts'}) if 'password' in payload['prompt'] else '')\n")
    hooks = make(ws, layers(("user_prompt_submit", {"command": block})))
    assert hooks.user_prompt("my password is x").decision == "deny"
    assert hooks.user_prompt("hello").decision is None
    ctx = script(tmp_path, "print(json.dumps({'context': 'branch: main'}))\n", "ctx.py")
    assert make(ws, layers(("user_prompt_submit", {"command": ctx}))).user_prompt("hi").context == "branch: main"


def test_a_hooks_object_is_false_when_empty(ws):
    assert not Hooks([], ws.root) and Hooks(layers(("pre_tool_use", {"command": "x"})), ws.root)


@pytest.mark.skipif(os.name != "nt", reason="the cmd.exe quoting path")
def test_a_command_with_quotes_works_through_cmd(ws, tools, tmp_path):
    cmd = script(tmp_path, "print(json.dumps({'decision': 'ask', 'reason': 'quoted'}))\n", "with space.py")
    assert make(ws, layers(("pre_tool_use", {"command": cmd}))).pre_tool(call("run_shell", command="ls"), tools["run_shell"]).reason == "quoted"
