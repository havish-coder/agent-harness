"""Lesson 52: git worktrees, so two sessions can change one project at the same time.

A worktree is a second checkout of the same repository, in its own folder and on its own branch: separate files, shared history. Two agents
(or you and an agent) editing one folder step on each other: one's half-finished edit breaks the other's tests, and `/undo` can't tell whose
change is whose. In two worktrees they can't.

`harness --worktree NAME` starts the session in `<repo>/.harness/worktrees/NAME` on the branch `harness/NAME`, made from the commit that is
checked out now (your uncommitted changes stay where they are), or resumed if it is already there. `.harness/` is a folder the search tools skip
and the edit tools ask about, so the main session neither finds nor quietly changes the copies.

When the session ends, the worktree is removed only if nothing in it would be lost: no uncommitted change or untracked file, and no commit that
no other branch has. Otherwise it is kept, and the harness prints how to carry on, merge or remove it. Any doubt (a git command that fails)
keeps it.
"""
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")     # one folder name: no "/", no "..", nothing git or Windows would read as special
FOLDER = Path(".harness") / "worktrees"


class WorktreeError(Exception):
    """Not a repository, a bad name, or a git command that failed. The message says which."""


@dataclass
class Worktree:
    name: str
    path: Path          # the worktree's own root
    branch: str
    repo: Path          # the main checkout
    workspace: Path     # where the session works: the same folder inside the worktree as the workspace was inside the repository
    created: bool       # False: an existing worktree was resumed


def git(cwd: Path, *args: str, check: bool = True) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise WorktreeError(f"git {args[0]}: {e}") from None
    if check and done.returncode != 0:
        raise WorktreeError((done.stderr or done.stdout).strip() or f"git {args[0]} failed")
    return done.stdout.strip() if done.returncode == 0 else ""


def enter(workspace: Path, name: str) -> Worktree:
    """Make the worktree NAME for the repository `workspace` is in, or resume it."""
    if not NAME.match(name) or ".." in name:
        raise WorktreeError(f"'{name}' can't name a worktree: use 1-40 letters, digits, '.', '_' or '-', starting with a letter or digit")
    workspace = workspace.resolve()
    top = Path(git(workspace, "rev-parse", "--show-toplevel")).resolve()
    common = Path(git(workspace, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    repo = common.parent                                           # the main checkout, even when started from inside a worktree
    path, branch = repo / FOLDER / name, f"harness/{name}"
    created = not (path / ".git").exists()
    if created:
        git(repo, "rev-parse", "--verify", "HEAD")                 # a repository without a commit has nothing to check out
        git(repo, "worktree", "prune")                             # forget worktrees whose folder was deleted by hand
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
            git(repo, "worktree", "add", str(path), branch)        # the branch outlived its folder: carry on from it, never reset it
        else:
            git(repo, "worktree", "add", "-b", branch, str(path), "HEAD")
        exclude = common / "info" / "exclude"                      # so the main checkout doesn't list the copies as new files
        try:
            lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
            if "/.harness/worktrees/" not in lines:
                exclude.parent.mkdir(parents=True, exist_ok=True)
                exclude.write_text("\n".join([*lines, "/.harness/worktrees/"]) + "\n", encoding="utf-8")
        except OSError:
            pass                                                   # ponytail: only cosmetic (git status shows the folder); nothing depends on it
    inside = path / workspace.relative_to(top)
    if not inside.is_dir():
        raise WorktreeError(f"{workspace.relative_to(top)} isn't in the worktree: it isn't in the commit the worktree was made from")
    return Worktree(name, path, branch, repo, inside, created)


def leave(wt: Worktree) -> str:
    """Remove the worktree if nothing in it would be lost, or keep it. Returns what happened, for the user."""
    try:
        changed = git(wt.path, "status", "--porcelain").splitlines()
        only_here = int(git(wt.path, "rev-list", "--count", "HEAD", "--not", f"--exclude={wt.branch}", "--branches"))
    except (WorktreeError, ValueError) as e:
        return f"kept the worktree {wt.name} ({e}): {wt.path}"
    if not changed and only_here == 0:
        try:
            git(wt.repo, "worktree", "remove", str(wt.path))      # without --force: git refuses if anything is there it would lose
            git(wt.repo, "branch", "-D", wt.branch)                # no commit is only on it (checked above)
            return f"removed the worktree {wt.name}: nothing in it was changed"
        except WorktreeError as e:
            return f"kept the worktree {wt.name} (git said: {e}): {wt.path}"
    parts = [f"{len(changed)} uncommitted change{'s' if len(changed) != 1 else ''}" if changed else "",
             f"{only_here} commit{'s' if only_here != 1 else ''} only on {wt.branch}" if only_here else ""]
    return (f"kept the worktree {wt.name} ({', '.join(p for p in parts if p)}): {wt.path}\n"
            f"  carry on:  harness --worktree {wt.name}\n"
            f"  merge:     commit there, then in your checkout: git merge {wt.branch}\n"
            f"  remove:    git worktree remove --force \"{wt.path}\" && git branch -D {wt.branch}")
