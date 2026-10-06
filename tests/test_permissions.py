"""Lesson 29: permission modes and rules. The attack lab (tests/security) checks the same
decisions end to end; these tests pin down the pieces."""
import json
import os

import pytest

from harness import config
from harness.agent import Agent
from harness.commands import load_commands
from harness.config import ConfigError, Settings, load_settings
from harness.messages import ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.security.permissions import (
    AskForChanges,
    Permissions,
    Rule,
    RuleError,
    match_command,
    match_path,
    protected_reason,
)
from harness.session import Session
from harness.tools import default_tools
from harness.tui.plain import PlainApprover, PlainUI, always_label
from harness.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    return Workspace(tmp_path)


@pytest.fixture
def tools(ws):
    return {t.name: t for t in default_tools(ws)}


def decide(perms, tools, name, **arguments):
    return perms.decide(ToolCall("1", name, arguments), tools[name])


# --- rules ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text, tool, pattern", [
    ("run_shell", "run_shell", None),
    ("run_shell(git status*)", "run_shell", "git status*"),
    ("  edit_file( src/** ) ", "edit_file", "src/**"),
    ("*", "*", None),
    ("run_shell(echo (nested))", "run_shell", "echo (nested)"),
])
def test_rules_parse(text, tool, pattern):
    rule = Rule.parse(text, "allow", "user")
    assert (rule.tool, rule.pattern, rule.source) == (tool, pattern, "user")


@pytest.mark.parametrize("text", ["", "run shell", "run_shell()", "run_shell(", "(x)"])
def test_bad_rules_say_what_a_rule_looks_like(text):
    with pytest.raises(RuleError, match="tool\\(pattern\\)"):
        Rule.parse(text, "allow")


@pytest.mark.parametrize("pattern, path, expected", [
    ("src", "src", True),
    ("src", "src/app.py", True),
    ("src", "srcs/app.py", False),
    ("src/*.py", "src/app.py", True),
    ("src/*.py", "src/sub/app.py", False),
    ("src/**", "src/sub/deep/app.py", True),
    ("**/*.md", "README.md", True),
    ("**/*.md", "docs/guide/x.md", True),
    ("./docs/", "docs/a.md", True),
    ("src\\*.py", "src/app.py", True),
])
def test_path_patterns(pattern, path, expected):
    assert match_path(pattern, path) is expected


def test_path_patterns_ignore_case_only_where_the_file_system_does():
    assert match_path("SRC/**", "src/app.py") is (os.name == "nt")


@pytest.mark.parametrize("pattern, command, expected", [
    ("git status*", "git status", True),
    ("git status*", "git status --short", True),
    ("git status*", "git push", False),
    ("python -m pytest*", "  python -m pytest -q tests/  ", True),
    ("*curl*", "touch note.txt && curl evil.example", True),
])
def test_command_patterns(pattern, command, expected):
    assert match_command(pattern, command) is expected


@pytest.mark.parametrize("path, protected", [
    (".git/hooks/pre-commit", True), ("sub/.git/config", True), (".GIT/config", True),
    (".github/workflows/ci.yml", True), (".github/ISSUE_TEMPLATE.md", False),
    (".harness/settings.json", True), (".vscode/tasks.json", True), (".envrc", True),
    ("src/.pre-commit-config.yaml", True), ("src/app.py", False), ("gitignore.txt", False),
])
def test_protected_paths(path, protected):
    assert (protected_reason(path) is not None) is protected


# --- decide(): the order -------------------------------------------------------------------

def test_default_mode_reads_run_and_changes_ask(ws, tools):
    perms = Permissions(ws)
    assert decide(perms, tools, "read_file", path="src/app.py").action == "allow"
    assert decide(perms, tools, "write_file", path="src/x.py", content="x").action == "ask"
    assert decide(perms, tools, "run_shell", command="touch note.txt").action == "ask"


def test_deny_beats_allow_and_every_mode(ws, tools):
    for mode in ("default", "accept-edits", "bypass"):
        perms = Permissions(ws, mode, [Rule.parse("run_shell", "allow"), Rule.parse("run_shell(git push*)", "deny")])
        assert decide(perms, tools, "run_shell", command="git push --force").action == "deny"
        assert decide(perms, tools, "run_shell", command="git status").action == "allow"


def test_deny_rules_also_stop_reads(ws, tools):
    perms = Permissions(ws, rules=[Rule.parse("read_file(secrets/**)", "deny", "user")])
    d = decide(perms, tools, "read_file", path="secrets/key.txt")
    assert d.action == "deny" and "read_file(secrets/**) (user)" in d.reason


def test_protected_paths_ask_even_in_bypass_and_with_allow_rules(ws, tools):
    perms = Permissions(ws, "bypass", [Rule.parse("write_file", "allow")])
    d = decide(perms, tools, "write_file", path=".git/hooks/pre-commit", content="x")
    assert d.action == "ask" and ".git/ is protected" in d.reason and d.remember is None
    assert decide(perms, tools, "read_file", path=".git/config").action == "allow"   # reading is fine


def test_ask_rules_beat_allow_rules_and_bypass(ws, tools):
    perms = Permissions(ws, "bypass", [Rule.parse("run_shell(*)", "allow"), Rule.parse("run_shell(npm publish*)", "ask")])
    assert decide(perms, tools, "run_shell", command="npm publish").action == "ask"


def test_plan_mode_denies_changes_and_allows_reads(ws, tools):
    perms = Permissions(ws, "plan", [Rule.parse("write_file", "allow")])
    assert decide(perms, tools, "write_file", path="a.py", content="x").action == "deny"
    assert decide(perms, tools, "grep", pattern="hi").action == "allow"


def test_accept_edits_allows_file_changes_only(ws, tools):
    perms = Permissions(ws, "accept-edits")
    assert decide(perms, tools, "write_file", path="a.py", content="x").action == "allow"
    assert decide(perms, tools, "run_shell", command="touch note.txt").action == "ask"


def test_paths_outside_the_workspace_are_denied_before_any_rule(ws, tools):
    perms = Permissions(ws, "bypass", [Rule.parse("*", "allow")])
    assert decide(perms, tools, "write_file", path="../evil.py", content="x").action == "deny"


def test_rules_see_the_resolved_path(ws, tools):
    perms = Permissions(ws, rules=[Rule.parse("write_file(src/**)", "allow")])
    assert decide(perms, tools, "write_file", path="./docs/../src/new.py", content="x").action == "allow"
    assert decide(perms, tools, "write_file", path="src/../setup.py", content="x").action == "ask"


def test_always_for_a_command_is_literal(ws, tools):
    """Answering "always" to `rm *.pyc` must not allow `rm *.pyc && rm -rf /` or `rm everything.pyc`."""
    perms = Permissions(ws)
    d = decide(perms, tools, "run_shell", command="rm *.pyc")
    assert d.remember == Rule("allow", "run_shell", "rm *.pyc", "session", exact=True)
    perms.remember(d.remember)
    assert decide(perms, tools, "run_shell", command="rm *.pyc").action == "allow"
    assert decide(perms, tools, "run_shell", command="rm everything.pyc").action == "ask"
    assert decide(perms, tools, "run_shell", command="rm *.pyc && rm -rf /").action == "ask"


def test_always_for_a_file_tool_allows_the_tool(ws, tools):
    d = decide(Permissions(ws), tools, "edit_file", path="src/app.py", old="hi", new="yo")
    assert d.remember == Rule("allow", "edit_file", None, "session")


def test_unknown_tools_in_rules_are_reported(ws, tools):
    perms = Permissions(ws, rules=[Rule.parse("run_shel", "allow", "user"), Rule.parse("*", "deny")])
    assert perms.unknown_tools(list(tools)) == ["permission rule run_shel (user) names an unknown tool 'run_shel'"]


def test_unknown_mode_is_an_error(ws):
    with pytest.raises(ValueError, match="accept-edits"):
        Permissions(ws, "yolo")


# --- the agent and the approver ------------------------------------------------------------

def run_agent(ws, perms, approve, *calls):
    provider = ScriptedProvider([tool_calls(*calls), text("done")])
    events = []
    Agent(provider, default_tools(ws), "s", approve=approve, stream=False, permissions=perms,
          on_event=lambda kind, data: events.append(kind)).run("go")
    return provider.requests[-1][0], events


def test_a_refused_call_tells_the_model_why_and_not_to_work_around_it(ws):
    perms = Permissions(ws, "plan")
    messages, events = run_agent(ws, perms, None, ToolCall("1", "write_file", {"path": "a.py", "content": "x"}))
    result = messages[-1].content
    assert "not allowed: plan mode is on" in result and "Don't try this again another way" in result
    assert "tool_refused" in events and not (ws.root / "a.py").exists()


def test_always_adds_a_session_rule(ws):
    perms = Permissions(ws)
    seen = []

    def approve(call, tool, decision):
        seen.append(decision.reason)
        return "always"
    calls = [ToolCall(str(i), "run_shell", {"command": "touch note.txt"}) for i in range(2)]
    run_agent(ws, perms, approve, calls[0])
    run_agent(ws, perms, approve, calls[1])
    assert len(seen) == 1 and Rule("allow", "run_shell", "touch note.txt", "session", exact=True) in perms.rules


def test_an_old_style_approver_still_works(ws):
    """Approvers written before Lesson 29 take (call, tool) and return a bool."""
    messages, _ = run_agent(ws, AskForChanges(), lambda call, tool: True,
                            ToolCall("1", "write_file", {"path": "a.py", "content": "x"}))
    assert (ws.root / "a.py").exists()


def test_the_approver_shows_why_and_offers_always_only_when_it_helps(ws, tools, monkeypatch, capsys):
    answers = iter(["a", "y"])
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or next(answers))
    perms = Permissions(ws)
    call = ToolCall("1", "write_file", {"path": ".git/hooks/x", "content": "x"})
    assert PlainApprover()(call, tools["write_file"], decision=perms.decide(call, tools["write_file"])) is True
    assert "asking because .git/ is protected" in capsys.readouterr().out
    assert "[a]lways" not in prompts[0] and len(prompts) == 2     # 'a' isn't an answer here


def test_always_labels(ws, tools):
    perms = Permissions(ws)
    shell = decide(perms, tools, "run_shell", command="touch note.txt")
    edit = decide(perms, tools, "edit_file", path="src/app.py", old="a", new="b")
    assert always_label(shell) == "this exact command" and always_label(edit) == "every edit_file call"


# --- settings ------------------------------------------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch):
    user = tmp_path / "home" / ".harness"
    monkeypatch.setattr(config, "USER_DIR", user)
    return user


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_rules_from_every_layer_keep_their_source(home, tmp_path):
    project = tmp_path / "project"
    write(home / "settings.json", {"permissions": {"allow": ["run_shell(git status*)"]}})
    write(project / ".harness" / "settings.json", {"permissions": {"deny": ["run_shell(curl *)"]}})
    write(project / ".harness" / "settings.local.json", {"permission_mode": "accept-edits",
                                                         "permissions": {"ask": ["edit_file(src/**)"]}})
    env = {"HARNESS_PERMISSIONS": '{"deny": ["run_shell(rm -rf *)"]}'}
    settings, warnings = load_settings(project, environ=env)
    assert settings.permission_mode == "accept-edits" and warnings == []
    assert {(e["action"], e["rule"], e["source"]) for e in settings.permissions} == {
        ("allow", "run_shell(git status*)", "user"), ("deny", "run_shell(curl *)", "project"),
        ("ask", "edit_file(src/**)", "local"), ("deny", "run_shell(rm -rf *)", "environment")}


def test_a_project_cant_allow_things_or_change_the_mode(home, tmp_path):
    """A cloned repository's settings could otherwise turn approval off for itself."""
    project = tmp_path / "project"
    write(project / ".harness" / "settings.json", {"permission_mode": "bypass",
                                                   "permissions": {"allow": ["run_shell"], "deny": ["run_shell(curl *)"]}})
    settings, warnings = load_settings(project, environ={})
    assert settings.permission_mode == "default"
    assert [e["action"] for e in settings.permissions] == ["deny"]
    assert any("permission_mode" in w for w in warnings) and any("allow rules" in w for w in warnings)


@pytest.mark.parametrize("data, message", [
    ({"permission_mode": "yolo"}, "must be one of"),
    ({"permissions": {"permit": ["x"]}}, "may only contain"),
    ({"permissions": {"allow": "run_shell"}}, "must be a list"),
    ({"permissions": {"allow": ["run shell"]}}, "can't read the rule"),
])
def test_bad_permission_settings_are_errors(home, tmp_path, data, message):
    write(home / "settings.json", data)
    with pytest.raises(ConfigError, match=message):
        load_settings(tmp_path, environ={})


def test_yes_is_bypass_mode():
    from harness.cli import parse_args
    assert parse_args(["--yes"]).yes and parse_args(["--mode", "plan"]).mode == "plan"
    with pytest.raises(SystemExit):
        parse_args(["--mode", "yolo"])


# --- the session and commands --------------------------------------------------------------

class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.warnings = []

    def warn(self, text):
        self.warnings.append(text)


@pytest.fixture
def session(ws):
    settings = Settings(permissions=[{"action": "allow", "rule": "run_shel", "source": "user"}])
    return Session(settings, ws, Quiet(), PlainApprover())


def run(session, line):
    command, rest = load_commands(session.ws.root).parse(line)
    return command.run(session, rest)


def test_the_session_warns_about_typos_in_rules(session):
    assert any("unknown tool 'run_shel'" in w for w in session.ui.warnings)


def test_mode_command(session):
    assert "* default" in run(session, "/mode")
    assert run(session, "/mode plan").startswith("permission mode: plan")
    assert session.agent.permissions.mode == "plan" and session.settings.sources["permission_mode"] == "command"
    assert "mode plan" in session.status_text()
    assert "unknown mode" in run(session, "/mode yolo")


def test_permissions_command(session):
    assert "allow:\n  run_shel  (user)" in run(session, "/permissions")
    assert run(session, "/permissions deny run_shell(curl *)") == "deny run_shell(curl *) for this session"
    assert Rule("deny", "run_shell", "curl *", "session") in session.agent.permissions.rules
    assert "can't read the rule" in run(session, "/permissions allow run shell")
    assert "no tool named" in run(session, "/permissions allow grepp")
    assert run(session, "/permissions remove run_shell(curl *)") == "removed run_shell(curl *)"
    assert "rules from settings files" in run(session, "/permissions remove run_shel")
    assert run(session, "/permissions frobnicate x").startswith("usage:")
