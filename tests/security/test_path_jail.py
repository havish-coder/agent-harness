"""Lesson 28: the path jail. Variations an attacker tries after `../` stops working.

Outcome tests go through the lab (what did the model see?); the unit tests at the end pin the
mechanism, `Workspace.path()`, so a refactor can't loosen it without a red test.
"""
import os

import pytest

from harness.workspace import OutsideWorkspace, Workspace
from tests.security.conftest import SECRET, call

ESCAPES = [
    "../outside/secret.txt",
    "src/../../outside/secret.txt",
    "./src/./../../outside/secret.txt",
    "..\\outside\\secret.txt",                      # backslashes
    "src/../../OUTSIDE/Secret.TXT",                  # case: Windows doesn't care, neither may we
]


@pytest.mark.parametrize("path", ESCAPES)
def test_spellings_of_dotdot(lab, path):
    if "\\" in path and os.name != "nt":
        pytest.skip("backslash is a normal character in file names outside Windows")
    assert SECRET not in lab.attack(call("read_file", path=path))


def test_absolute_paths_in_other_forms(lab):
    secret = lab.outside / "secret.txt"
    forms = [secret.as_posix(), str(secret)]
    if os.name == "nt":
        forms += [f"\\\\?\\{secret}",                                   # extended-length prefix
                  f"\\\\localhost\\{secret.drive[0]}$\\{str(secret)[3:]}",  # administrative share (UNC)
                  f"{secret.drive}{str(secret)[2:]}".lower()]
    for i, form in enumerate(forms):
        assert SECRET not in lab.attack(call("read_file", f"a{i}", path=form)), form


def test_a_sibling_folder_whose_name_starts_like_the_root(lab):
    """The classic string-prefix bug: '/tmp/ws-evil'.startswith('/tmp/ws') is True."""
    evil = lab.base / (lab.root.name + "-evil")
    evil.mkdir()
    (evil / "x.txt").write_text(SECRET, encoding="utf-8")
    assert SECRET not in lab.attack(call("read_file", path=f"../{evil.name}/x.txt"))


def test_every_tool_is_jailed(lab):
    seen = lab.attack(call("list_dir", "a1", path=".."),
                      call("glob", "a2", pattern="*.txt", path="../outside"),
                      call("grep", "a3", pattern="SECRET", path="../outside/secret.txt"),
                      call("edit_file", "a4", path="../outside/secret.txt", old_string="TOP", new_string="X"),
                      call("write_file", "a5", path="../outside/new.txt", content="x"))
    assert SECRET not in seen and seen.count("outside the workspace") == 5
    assert (lab.outside / "secret.txt").read_text(encoding="utf-8").startswith("TOP")
    assert not (lab.outside / "new.txt").exists()


def test_links_inside_the_workspace_are_named_but_never_entered(lab):
    if not lab.has_link:
        pytest.skip("can't create a symlink or junction here")
    seen = lab.attack(call("grep", "a1", pattern="TOP-SECRET"),          # whole workspace
                      call("glob", "a2", pattern="*.txt"),
                      call("list_dir", "a3", path="."),
                      call("list_dir", "a4", path="link"))
    assert SECRET not in seen and "link/secret.txt" not in seen
    assert "link  (link outside the workspace)" in seen


def test_the_workspace_snapshot_doesnt_follow_links(lab):
    from harness.tools.fs import workspace_snapshot
    if not lab.has_link:
        pytest.skip("can't create a symlink or junction here")
    snapshot = workspace_snapshot(lab.ws)
    assert "secret.txt" not in snapshot and "link  (link outside the workspace)" in snapshot


def test_mentions_outside_the_workspace_are_not_attached(lab):
    from harness.mentions import expand_mentions
    text, attached = expand_mentions("look at @../outside/secret.txt", lab.ws)
    assert attached == [] and SECRET not in text


def test_added_folders_are_allowed(lab):
    ws = Workspace(lab.root, extra_dirs=[lab.outside])
    assert ws.path(str(lab.outside / "secret.txt")) == (lab.outside / "secret.txt").resolve()
    with pytest.raises(OutsideWorkspace):
        ws.path("../../elsewhere.txt")


# --- the mechanism ------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "notes.txt:hidden",          # NTFS alternate data stream
    "notes.txt::$DATA",
    "src/app.py.",               # trailing dot: Windows opens src/app.py
    "src/app.py ",               # trailing space: same
    ".git./hooks/pre-commit",    # sneaking a protected folder past a name check
    "NUL", "con.txt", "src/COM1.log", "aux",
])
def test_names_windows_reinterprets_are_refused(tmp_path, name):
    with pytest.raises(OutsideWorkspace):
        Workspace(tmp_path).path(name)


@pytest.mark.parametrize("name", ["notes.txt", "src/app.py", ".", "a/b/../c.txt", "console.py",
                                  "nullable.txt", ".gitignore", "C:/" if os.name != "nt" else "src/x"])
def test_ordinary_names_are_fine(tmp_path, name):
    p = Workspace(tmp_path).path(name)
    assert p == tmp_path.resolve() or p.is_relative_to(tmp_path.resolve())


def test_the_root_itself_and_its_absolute_path_are_inside(tmp_path):
    ws = Workspace(tmp_path)
    assert ws.path(".") == ws.root and ws.path(str(tmp_path)) == ws.root
    assert ws.path(str(tmp_path / "a.txt")) == ws.root / "a.txt"


def test_a_project_cant_widen_the_jail(tmp_path, monkeypatch):
    """T11: additional_directories grants access, so only your own settings may set it."""
    import json

    from harness.config import load_settings
    monkeypatch.setattr("harness.config.USER_DIR", tmp_path / "home")
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "settings.json").write_text(json.dumps({"additional_directories": ["C:/"]}))
    settings, warnings = load_settings(tmp_path, environ={})
    assert settings.additional_directories == []
    assert any("can't set 'additional_directories'" in w for w in warnings)
    (tmp_path / ".harness" / "settings.local.json").write_text(json.dumps({"additional_directories": ["../shared"]}))
    assert load_settings(tmp_path, environ={})[0].additional_directories == ["../shared"]
    env = {"HARNESS_ADDITIONAL_DIRECTORIES": os.pathsep.join(["a", "b"])}
    assert load_settings(tmp_path, environ=env)[0].additional_directories == ["a", "b"]
