"""Lesson 35: the sandbox wrappers. These build command lines and are tested as such: nothing here
starts bwrap or sandbox-exec, which don't exist on every machine. A test that really runs one is in
tests/security and is skipped where there is no sandbox."""
import json
import os
import sys
from pathlib import Path

import pytest

from harness import config
from harness.config import ConfigError, Settings, load_settings
from harness.security.sandbox import (
    Sandbox,
    bubblewrap_argv,
    detect,
    hint,
    protected_paths,
    seatbelt_argv,
    seatbelt_profile,
    seatbelt_quote,
)
from harness.session import Session
from harness.tools import default_tools
from harness.tui.plain import PlainApprover, PlainUI
from harness.workspace import Workspace


@pytest.fixture
def root(tmp_path):
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".envrc").write_text("x", encoding="utf-8")
    (tmp_path / "src").mkdir()
    return tmp_path


def test_protected_paths_are_the_ones_that_exist(root):
    found = {p.relative_to(root).as_posix() for p in protected_paths(root)}
    assert found == {".git", ".github/workflows", ".envrc"}          # .harness, .vscode ... don't exist here


def test_bubblewrap_argv_orders_the_mounts_so_protection_wins(root):
    argv = bubblewrap_argv("/usr/bin/bwrap", ["bash", "-c", "ls"], root, root, protected_paths(root), network=True)
    text = " ".join(argv)
    assert argv[0] == "/usr/bin/bwrap" and argv[-4:] == ["--", "bash", "-c", "ls"] or argv[-3:] == ["bash", "-c", "ls"]
    assert argv.index("--") < len(argv) - 1 and argv[argv.index("--") + 1:] == ["bash", "-c", "ls"]
    assert "--ro-bind / /" in text and f"--bind {root} {root}" in text
    # a later mount of the same path wins: the writable workspace first, then the protected places read-only
    writable = text.index(f"--bind {root} {root}")
    for name in (".git", ".envrc"):
        assert text.index(f"--ro-bind {root / name} {root / name}") > writable
    assert "--unshare-pid" in argv and "--die-with-parent" in argv and "--new-session" in argv
    assert "--unshare-net" not in argv
    assert "--chdir" in argv and argv[argv.index("--chdir") + 1] == str(root)


def test_blocking_the_network_adds_unshare_net(root):
    argv = bubblewrap_argv("bwrap", ["true"], root, root, [], network=False)
    assert "--unshare-net" in argv


def test_tmp_is_fresh_and_comes_before_the_workspace_bind(root):
    """If the workspace lives under /tmp (it does in tests), the fresh /tmp must not hide it."""
    argv = bubblewrap_argv("bwrap", ["true"], root, root, [], network=True)
    assert argv.index("--tmpfs") < argv.index("--bind")


def test_seatbelt_profile_allows_writes_in_the_workspace_and_denies_protected_places_after(root):
    profile = seatbelt_profile(root, protected_paths(root), network=True)
    lines = profile.splitlines()
    assert lines[:3] == ["(version 1)", "(allow default)", "(deny file-write*)"]
    allow = next(i for i, line in enumerate(lines) if line.startswith("(allow file-write*"))
    denies = [i for i, line in enumerate(lines) if line.startswith("(deny file-write* (subpath")]
    assert len(denies) == 3 and all(i > allow for i in denies)           # the last matching rule wins
    assert f"(subpath {seatbelt_quote(root)})" in lines[allow] and "network" not in profile


def test_seatbelt_can_cut_the_network_and_quotes_paths():
    assert seatbelt_profile(Path("/w"), [], network=False).splitlines()[-1] == "(deny network*)"
    assert seatbelt_quote('/a "b"\\c') == '"/a \\"b\\"\\\\c"'
    argv = seatbelt_argv("/usr/bin/sandbox-exec", ["bash", "-c", "ls"], Path("/w"), [], True)
    assert argv[:2] == ["/usr/bin/sandbox-exec", "-p"] and argv[3:] == ["bash", "-c", "ls"]


def test_wrap_picks_the_right_builder_and_resolves_paths(root):
    bw = Sandbox("bubblewrap", "bwrap").wrap(["sh", "-c", "x"], root, root, network=False)
    assert bw[0] == "bwrap" and "--unshare-net" in bw
    sb = Sandbox("sandbox-exec", "sandbox-exec").wrap(["sh", "-c", "x"], root, root)
    assert sb[:2] == ["sandbox-exec", "-p"]


def test_the_description_says_what_the_sandbox_does():
    text = Sandbox("bubblewrap", "bwrap").describe(network=False)
    assert "bubblewrap" in text and "write only inside the workspace" in text and "network blocked" in text
    assert "network allowed" in Sandbox("sandbox-exec", "x").describe()


@pytest.mark.parametrize("platform, tool, name", [("linux", "bwrap", "bubblewrap"), ("linux2", "bwrap", "bubblewrap"),
                                                  ("darwin", "sandbox-exec", "sandbox-exec")])
def test_detect_finds_the_tool_for_the_platform(platform, tool, name):
    found = detect(platform, lambda program: f"/usr/bin/{program}" if program == tool else None)
    assert found == Sandbox(name, f"/usr/bin/{tool}")
    assert detect(platform, lambda program: None) is None


def test_windows_has_no_sandbox_and_the_hint_says_what_to_use():
    assert detect("win32", lambda program: "/anything") is None
    assert "WSL 2" in hint("win32") and "bubblewrap" in hint("linux") and "sandbox-exec" in hint("darwin")
    assert "no supported sandbox" in hint("freebsd")


# --- the shell tool and the session --------------------------------------------------------

class Recorder:
    """A sandbox that doesn't wrap anything, but records that it was asked to, and what the command was."""
    name = "recorder"

    def __init__(self):
        self.calls = []

    def wrap(self, argv, cwd, root, network=True):
        self.calls.append((list(argv), Path(cwd), Path(root), network))
        return argv

    def describe(self, network=True):
        return "commands run in a recorder sandbox"


def test_the_shell_tool_runs_commands_through_the_sandbox(tmp_path):
    ws = Workspace(tmp_path)
    recorder = Recorder()
    run = {t.name: t for t in default_tools(ws, sandbox=recorder, sandbox_network=False)}["run_shell"]
    out = run.fn(command=f'"{sys.executable}" -c "print(41 + 1)"')
    assert "42" in out and len(recorder.calls) == 1
    argv, cwd, wrapped_root, network = recorder.calls[0]
    assert cwd == tmp_path and wrapped_root == tmp_path and network is False
    assert "Commands run in a recorder sandbox." in run.description


def test_no_sandbox_means_no_note_and_direct_execution(tmp_path):
    run = {t.name: t for t in default_tools(Workspace(tmp_path))}["run_shell"]
    assert "sandbox" not in run.description and "exit code 0" in run.fn(command=f'"{sys.executable}" -c "pass"')


def test_when_a_sandbox_is_required_and_missing_commands_are_refused(tmp_path):
    run = {t.name: t for t in default_tools(Workspace(tmp_path), sandbox_required=True)}["run_shell"]
    out = run.fn(command="echo should-not-run")
    assert out.startswith("Error: commands are switched off") and "should-not-run" not in out.split("(")[0]


class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.warnings = []

    def warn(self, text):
        self.warnings.append(text)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    return tmp_path / "home"


def test_the_session_uses_a_sandbox_when_there_is_one(home, tmp_path, monkeypatch):
    found = Sandbox("bubblewrap", "/usr/bin/bwrap")
    monkeypatch.setattr("harness.session.detect_sandbox", lambda: found)
    session = Session(Settings(), Workspace(tmp_path), Quiet(), PlainApprover())
    run = {t.name: t for t in session.agent.tools}["run_shell"]
    assert session.sandbox == found and "bubblewrap sandbox" in run.description


def test_sandbox_off_never_looks_for_one(home, tmp_path, monkeypatch):
    monkeypatch.setattr("harness.session.detect_sandbox", lambda: pytest.fail("looked for a sandbox"))
    assert Session(Settings(sandbox="off"), Workspace(tmp_path), Quiet(), PlainApprover()).sandbox is None


def test_sandbox_on_without_one_warns_and_switches_commands_off(home, tmp_path, monkeypatch):
    monkeypatch.setattr("harness.session.detect_sandbox", lambda: None)
    session = Session(Settings(sandbox="on"), Workspace(tmp_path), Quiet(), PlainApprover())
    assert any("sandbox is \"on\" but this machine has none" in w for w in session.ui.warnings)
    run = {t.name: t for t in session.agent.tools}["run_shell"]
    assert run.fn(command="echo hi").startswith("Error: commands are switched off")


def test_auto_without_a_sandbox_is_quiet(home, tmp_path, monkeypatch):
    monkeypatch.setattr("harness.session.detect_sandbox", lambda: None)
    session = Session(Settings(sandbox="auto"), Workspace(tmp_path), Quiet(), PlainApprover())
    assert session.sandbox is None and not any("sandbox" in w for w in session.ui.warnings)


def test_the_sandbox_settings_are_validated_and_not_accepted_from_projects(home, tmp_path):
    project = tmp_path / "project"
    (project / ".harness").mkdir(parents=True)
    (project / ".harness" / "settings.json").write_text(json.dumps({"sandbox": "off", "sandbox_network": True}), encoding="utf-8")
    settings, warnings = load_settings(project, environ={})
    assert settings.sandbox == "auto" and sum("project settings can't set" in w for w in warnings) == 2
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps({"sandbox": "maybe"}), encoding="utf-8")
    with pytest.raises(ConfigError, match="'sandbox' must be one of off, auto, on"):
        load_settings(tmp_path, environ={})


@pytest.mark.skipif(not sys.platform.startswith("linux") or not os.path.exists("/usr/bin/bwrap"), reason="needs bubblewrap")
def test_a_real_bubblewrap_blocks_a_write_to_git(tmp_path):
    """Runs only where bwrap is installed: the command that builds the path at run time can't write there."""
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    run = {t.name: t for t in default_tools(Workspace(tmp_path), sandbox=detect(), sandbox_network=False)}["run_shell"]
    out = run.fn(command="python3 -c \"open('.g'+'it/hooks/pre-commit','w').write('x')\"")
    assert "Read-only file system" in out and not (tmp_path / ".git" / "hooks" / "pre-commit").exists()
