# 0050. A git worktree per session on request, removed at the end only if nothing in it would be lost

- **Status:** Accepted
- **Date:** 2026-10-08

## Context
Everything the agent changes, it changes in the workspace folder. Two sessions in one folder (two agents, or an agent and you) interfere: one's
half-finished edit breaks the other's test run, a formatter run by one rewrites the other's change, and file history (ADR 0041) records edits
without knowing whose they are. Sub-agents (ADR 0045) avoid this by running one at a time; parallel sessions can't.

Git already has the tool: a **worktree** is another checkout of the same repository, in its own folder and on its own branch, sharing the
history. Measured on this repository (267 tracked files): `git worktree add` took a median of **1.5 s**, removal **0.9 s**, and the worktree was
**2.0 MB** of files.

## Options
1. **Nothing**: run parallel sessions in separate clones by hand.
2. **A flag that starts the session in a worktree** (`--worktree NAME`), made or resumed, cleaned up at the end.
3. **Tools for the model** to enter and leave a worktree mid-session (the reference has `EnterWorktree` / `ExitWorktree`).
4. **Worktree isolation for sub-agents**: each delegated worker in a fresh worktree.

## Decision
Option 2 (`harness/worktree.py`, `--worktree`).

- **Where**: `<main repository>/.harness/worktrees/NAME`, on the branch `harness/NAME`, made from `HEAD` (the commit checked out now; uncommitted
  changes stay where they are). From inside a worktree, a new one still goes under the main repository, so they never nest. `.harness/` is
  already skipped by the search tools and protected for edits, and `/.harness/worktrees/` is added to `.git/info/exclude` so `git status` in
  the checkout stays clean.
- **Names** are one folder name of 1-40 characters from `[A-Za-z0-9._-]`, starting with a letter or digit, without `..`: no path escapes, nothing
  git reads as an option.
- **Resume, never reset.** The same name resumes the worktree. If its folder was deleted but the branch survives, the branch is checked out
  again (`git worktree add PATH BRANCH`), not recreated with `-B`, which would throw its commits away.
- **Removed only if nothing would be lost**: `git status --porcelain` is empty (no edited, deleted or new file) **and** no commit on the branch is
  missing from every other branch (`git rev-list --count HEAD --not --exclude=harness/NAME --branches`). Then `git worktree remove` (without
  `--force`, so git refuses if something is there after all) and `git branch -D`. Otherwise it is kept and the harness prints the commands to
  carry on, merge and remove. Any git failure keeps it: removal is the irreversible direction.
- **The session sees the worktree as its workspace**: the path jail, chats, memory, journal and file history are the worktree's. The workspace
  folder maps to the same folder inside the worktree. A trusted folder's worktree is trusted (same files), and the `.env` of the user's own
  folder is still loaded (git doesn't copy ignored files).
- **Cleanup runs at exit** (`atexit`), after the session has stopped its background tasks and MCP servers, also after `--show-config` or a
  start-up error.

## Consequences
- Parallel sessions on one repository are a flag away; a session that changed nothing leaves nothing behind.
- What the agent did is a branch: reviewed, merged or dropped with ordinary git.
- It needs git and a repository with a commit; a folder that isn't one is an error, not a silent fallback.
- **Not a sandbox.** A worktree separates files, not permissions: commands reach the rest of the disk as before, and the repository's hooks and
  branches are shared.
- Not done (YAGNI): moving a running session into a worktree (option 3, which would mean rebuilding the session's workspace-bound parts
  mid-chat), sub-agents in their own worktrees (option 4, the natural next step for parallel delegation), basing a worktree on a remote branch or
  a pull request, copying ignored files such as `node_modules` into it.
