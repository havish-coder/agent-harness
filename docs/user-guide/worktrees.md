# Worktrees: a checkout of your own for each session

Two agents working in one folder step on each other: one's half-finished edit breaks the other's tests, one runs the formatter over the other's
change, and `/undo` can't tell whose edit is whose. The same goes for you and an agent: while it works, your folder is not yours.

A **git worktree** is a second checkout of the same repository, in its own folder and on its own branch. The files are separate; the history is
shared. Start a session in one with `--worktree`:

```text
> harness --worktree fix-cart
Agent harness · ollama · qwen3:4b-instruct · C:\code\shop\.harness\worktrees\fix-cart
/help commands · @file attaches a file · Esc or Ctrl+C stops a running task
worktree fix-cart (new), branch harness/fix-cart: your own checkout is not changed
```

The agent now works in `.harness/worktrees/fix-cart`, on the branch `harness/fix-cart`. Open another terminal and start a second session in
another worktree, or keep working in your own checkout: nothing one does touches the others' files.

## Where it comes from
- The worktree is made from **the commit checked out now**. Changes you haven't committed stay in your own folder; commit them first if the
  agent should start from them.
- It lives in `<repository>/.harness/worktrees/NAME`. The harness adds that folder to the repository's `.git/info/exclude`, so `git status`
  in your checkout doesn't list it, and the search tools skip `.harness/`, so a session in your checkout doesn't find the copies.
- If `--workspace` is a folder inside the repository, the session works in the same folder inside the worktree.
- `--worktree NAME` again resumes the same worktree, with whatever was left in it. A branch whose folder you deleted by hand is checked out
  again, never reset.
- A worktree of a folder you [trusted](untrusted-content.md) is trusted: it holds the same files. The `.env` of your own folder is still read
  (git doesn't copy ignored files into a worktree).

A name is 1 to 40 letters, digits, `.`, `_` or `-`, starting with a letter or digit.

## When the session ends
The harness looks at what is in the worktree:

- **Nothing changed** (no edited or new file, and no commit that only its branch has): the worktree and its branch are removed.
  ```text
  removed the worktree fix-cart: nothing in it was changed
  ```
- **Something would be lost**: it is kept, and you are told how to finish (after the agent fixed a bug; the folder renamed):
  ```text
  kept the worktree fix-cart (1 uncommitted change): C:\code\shop\.harness\worktrees\fix-cart
    carry on:  harness --worktree fix-cart
    merge:     commit there, then in your checkout: git merge harness/fix-cart
    remove:    git worktree remove --force "C:\code\shop\.harness\worktrees\fix-cart" && git branch -D harness/fix-cart
  ```

If a git command fails while checking, the worktree is kept. Once its branch is merged, the next time a session in it ends cleanly it is removed.

## Bringing the work back
The agent's changes are ordinary changes on a branch. Review them (`git -C .harness/worktrees/fix-cart diff`), commit them in the worktree,
and merge or cherry-pick the branch in your checkout as you would any other.

## What it isn't
A worktree keeps sessions out of each other's files; it is **not a sandbox**. The agent in it is held to the worktree folder like any
[workspace](workspace.md), but a command it runs can reach the rest of your disk as it always could (see [the command sandbox](sandbox.md)), and
the worktree shares the repository's branches, history and git hooks.

It needs a git repository with at least one commit.

## What it measured
On this project's own repository (267 tracked files): making a worktree took a median of **1.5 s**, removing one **0.9 s**, and a worktree was
**2.0 MB** of files, the history being shared rather than copied. In a real run, `qwen3:4b-instruct` fixed the sample project's subtotal bug in
`--worktree fix-cart`; the file in the worktree had the fix and the same file in the checkout still had the bug.
