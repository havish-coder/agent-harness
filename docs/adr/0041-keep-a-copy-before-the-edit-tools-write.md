# 0041. Keep a copy of a file just before an edit tool writes it, and put it back only if nobody has touched it since

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
An agent that edits files will, sooner or later, edit them wrongly, and the user needs a way back that doesn't depend on the project being in git, on the agent behaving, or on remembering what changed. Two things
make it harder than "save a backup":
- the **conversation** and the **files** are two histories, and going back in one without the other leaves the model believing things that aren't true;
- a restore that overwrites a file the user has edited since is **worse than no undo**.

## Options
1. **Use git** (a stash, a commit per request, a shadow repository). Needs a repository, which not every project has; a commit per request puts the agent's history in the user's; a stash fights with the user's own work.
2. **Watch the whole workspace** and snapshot changed files. Covers shell commands too, but needs a watcher, can't see a file's content from *before* the change unless everything is copied first, and is expensive on a large tree.
3. **Ask each tool to say what it changed** (a "file changes" list from every tool, as a plug-in interface). Right in principle; there are two file-changing tools today.
4. **Copy in the two edit tools, just before they write,** log it per request, and restore with checks.

## Decision
Option 4 (`harness/filehistory.py`), with these rules:

- **The copy is made before the write**, from the file's exact bytes (so line endings and encodings survive), stored by its SHA-256 (the same content is kept once; editing a file 30 times in one request keeps one copy of its
  original). The log line is written before the write too: a crash can leave a line for a write that didn't happen (undo then finds the file already as it was), never a write with no way back.
- **A request is the unit.** Every user message the agent starts gets an id (`Message.checkpoint`), the history groups changes by it, and `/undo` means "the last request that changed files". `/rewind N` puts back every request from N and, by default,
  cuts the conversation at the same message.
- **Restore only what is still the agent's.** Each change records the hash of what was written; a file whose current content is neither that nor the original is a *conflict*: skipped and reported, unless `force`, which first keeps the version being replaced.
  Missing or damaged copies (checked by hash) are an error for that file only, never written.
- **Fail open when keeping a copy fails.** A full disk or a huge file doesn't stop the edit (that would make an agent unusable for a storage problem); it says once that this change can't be undone.
- **Not covered, and said so:** files changed by `run_shell`. The log records that a request ran such a command, and listing and undo say that it can't be undone. A watcher (option 2) is the way to cover them, and a later lesson may add one.
- **It is the user's command.** No tool for the model, the history is outside the paths the tools can reach, restored paths go through the path jail, and the prompt text kept for display has secrets hidden.
- **The conversation side reuses the chat log**: a rewind appends the `rolled_back` operation that already exists ([ADR 0037](0037-chats-as-append-only-logs-of-messages-and-operations.md)); replaying the log gives the rewound conversation, and nothing is rewritten.
- **The model is told what it can't see**: with the next request, a one-line note from the harness says which files were put back (after `/undo` or `/rewind N code`), or which files still hold changes from the part of the conversation that was removed (`chat`).
- **Taint is not rewound.** Forgetting a page doesn't make what the agent did after reading it safe.

Stored in the user's folder next to the chats (`history/<chat>.jsonl`, `history/blobs/`), removed with the chat; setting `file_history` (default on), barred from project settings.

## Consequences
- Undo works in any folder, with or without git, in any interface (the Session has `undo` and `rewind`; the web UI will call them), and survives closing the terminal: a resumed chat can still undo.
- Each change costs a copy of the old file (measured: 6 to 20 ms per copy and 35 to 57 ms per file restored on Windows, files of 1 KB to 1 MB), and a file edited in many separate requests is kept once per request: 30 requests editing a 109 KB file kept 3.2 MB, 30 edits in one request kept 109 KB.
- Commands are the gap. A project where the agent mostly runs commands needs git; the listing says which requests ran commands.
- The history is a list the user can read and the harness can check; its guarantees are tested with a random round trip (`scripts/history_lab.py roundtrip`): 300 of 300 random chats rewound byte for byte, and 300 of 300 with a user edit in the way left intact. That experiment **found a real bug** (empty folders left behind when two requests wrote into the same new
  folder, 52 of 300 cases) before it shipped.
- Messages gained a field (`checkpoint`), ignored when messages are compared, absent from the wire formats and from recorded cassettes.
- After an undo the model may still believe the edit is there. Measured (`scripts/history_lab.py stale`): asked to quote a line after its edit of that line was undone, a small model said the edit was still there in **6 of 6** runs when the harness said nothing, and quoted the restored line in **6 of 6** when the harness added a one-line note to the next request. Hence the note.
