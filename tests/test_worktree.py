"""Lesson 52: worktrees. Real git repositories in a temporary folder."""
import subprocess

import pytest

from harness.cli import parse_args
from harness.worktree import WorktreeError, enter, git, leave


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                 ["config", "core.autocrlf", "false"], ["add", "."], ["commit", "-qm", "first"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


def test_a_worktree_is_made_on_its_own_branch_inside_the_repository(repo):
    wt = enter(repo, "fix-cart")
    assert wt.created and wt.path == repo / ".harness" / "worktrees" / "fix-cart" and wt.branch == "harness/fix-cart"
    assert (wt.path / "app" / "main.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert git(wt.path, "branch", "--show-current") == "harness/fix-cart"
    assert "/.harness/worktrees/" in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert git(repo, "status", "--porcelain") == ""                  # the main checkout doesn't see the copy


def test_the_workspace_maps_to_the_same_folder_inside_the_worktree(repo):
    wt = enter(repo / "app", "x")
    assert wt.workspace == wt.path / "app"


def test_the_same_name_resumes_the_same_worktree(repo):
    first = enter(repo, "x")
    (first.path / "app" / "new.py").write_text("x = 1\n", encoding="utf-8")
    again = enter(repo, "x")
    assert not again.created and again.path == first.path and (again.path / "app" / "new.py").exists()


def test_nothing_changed_means_it_is_removed_with_its_branch(repo):
    wt = enter(repo, "x")
    assert leave(wt) == "removed the worktree x: nothing in it was changed"
    assert not wt.path.exists() and git(repo, "branch", "--list", "harness/x") == ""


def test_an_uncommitted_change_keeps_it_and_says_how_to_finish(repo):
    wt = enter(repo, "x")
    (wt.path / "app" / "main.py").write_text("print('changed')\n", encoding="utf-8")
    said = leave(wt)
    assert said.startswith("kept the worktree x (1 uncommitted change)") and "harness --worktree x" in said and "git merge harness/x" in said
    assert wt.path.exists()


def test_a_new_file_keeps_it_too(repo):
    wt = enter(repo, "x")
    (wt.path / "notes.txt").write_text("todo\n", encoding="utf-8")
    assert leave(wt).startswith("kept the worktree x (1 uncommitted change)")


def test_a_commit_only_on_its_branch_keeps_it_and_one_merged_elsewhere_does_not(repo):
    wt = enter(repo, "x")
    (wt.path / "app" / "main.py").write_text("print('fixed')\n", encoding="utf-8")
    git(wt.path, "commit", "-qam", "fix")
    assert leave(wt).startswith("kept the worktree x (1 commit only on harness/x)")
    git(repo, "merge", "-q", "harness/x")                           # now main has it: removing the branch loses nothing
    assert leave(wt) == "removed the worktree x: nothing in it was changed"


def test_a_branch_whose_folder_was_deleted_is_carried_on_not_reset(repo):
    wt = enter(repo, "x")
    (wt.path / "app" / "main.py").write_text("print('kept')\n", encoding="utf-8")
    git(wt.path, "commit", "-qam", "work")
    git(repo, "worktree", "remove", "--force", str(wt.path))         # the folder goes; the branch and its commit stay
    again = enter(repo, "x")
    assert again.created and (again.workspace / "app" / "main.py").read_text(encoding="utf-8") == "print('kept')\n"


def test_a_worktree_started_from_a_worktree_belongs_to_the_main_repository(repo):
    first = enter(repo, "one")
    second = enter(first.path / "app", "two")
    assert second.path == repo / ".harness" / "worktrees" / "two" and second.workspace == second.path / "app"


@pytest.mark.parametrize("name", ["", "../x", "a/b", "a\\b", "-x", ".hidden", "x" * 41, "x..y", "with space"])
def test_names_that_could_escape_or_confuse_git_are_refused(repo, name):
    with pytest.raises(WorktreeError, match="can't name a worktree"):
        enter(repo, name)


def test_a_folder_that_is_not_a_repository_is_an_error(tmp_path):
    with pytest.raises(WorktreeError, match="not a git repository"):
        enter(tmp_path, "x")


def test_a_repository_without_a_commit_is_an_error(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    with pytest.raises(WorktreeError):
        enter(tmp_path, "x")


def test_a_workspace_that_is_not_committed_is_an_error(repo):
    (repo / "scratch").mkdir()
    (repo / "scratch" / "a.txt").write_text("a", encoding="utf-8")
    with pytest.raises(WorktreeError, match="isn't in the worktree"):
        enter(repo / "scratch", "x")


def test_the_flag_is_parsed():
    assert parse_args(["--worktree", "fix-cart"]).worktree == "fix-cart" and parse_args([]).worktree is None
