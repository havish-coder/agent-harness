# 0037. Save each chat as an append-only log of messages and operations, and rebuild it by replaying

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
Until now a conversation lived in memory: closing the terminal ended it. We want chats that survive, that a project can have several of, that can be
resumed from the terminal (and later from a browser), and that can be forked. The difficulty is that the conversation the model sees is **not just the
messages that were added**. The harness also changes it:
- it replaces old results with notes ([ADR 0035](0035-clear-old-tool-results-before-anything-else.md)),
- it replaces the older part with a summary ([ADR 0036](0036-summarise-when-clearing-is-not-enough.md)),
- it removes the messages of a turn that failed.
A saved chat must give back the conversation as it stood, or a resumed chat behaves differently from the one that was left (all the cleared results back, which no
longer fit; rolled-back messages reappearing; a tool call with no result).

## Options
1. **Rewrite a snapshot** of the message list after each turn. Simple to replay. The whole file is rewritten every turn, a crash during the write can corrupt all of it, and what a
   summary replaced is gone (the user can no longer export or search it).
2. **Append only the messages.** Crash-safe, keeps everything, but can't reproduce clears, summaries or rollbacks: it saves the messages, not the conversation.
3. **Append messages and the operations on them; replay to rebuild.** Crash-safe, keeps everything, exact.
4. **A tree of messages with a parent id on each**, so branches and compaction boundaries are links (the design of the reference tool we studied). Handles forks natively; needs a tree
   reader and a rule for how a summary breaks the chain.

## Decision
Option 3, in `harness/chats.py`.

- **One file per chat**: `<user folder>/projects/<folder name>-<8 hex of the folder's path>/chats/<date>-<time>-<hex>.jsonl`, in the user's folder and not in the workspace, so a
  chat (which contains what the agent read) can't be committed by accident. A chat is created when its first message is written.
- **Entries** (one JSON object per line, compact separators): `chat` (the header), `message`, `clear` (call ids), `compact` (how many messages the summary replaced, and the summary), `rollback`
  (the length to keep), `title`. Unknown kinds are ignored, so a newer file can be read by an older program.
- **The agent says what it does**: every message goes through `Agent.add()`, which emits a `message` event; a rolled-back turn emits `rolled_back`; clearing and summarising already
  emit events. The session turns each into a line **as it happens**, not at the end of the turn, so closing the terminal during a long task loses at most the step that was running.
- **Replay applies the entries in order**: messages append; `clear` regenerates the same note the agent made (the note is a pure function of the call and the original text); `compact`
  replaces the first N messages with the summary and moves them to the archive; `rollback` truncates. A line that can't be read is skipped and counted (a crash can only damage the last);
  an unfinished tool exchange at the end is dropped and reported, and the log is told (a `rollback` line) so the file and the conversation agree.
- **The system prompt is not saved.** A resumed chat gets today's, with the current date, git state, file listing and settings.
- **What a resume restores beyond the messages:** the summaries' archive, the number of summaries, and the **taint**: any `<untrusted source="...">` fence in the chat marks the resumed chat as having
  read untrusted content, because otherwise resuming would reset the one thing that stops a broad approval after an injection ([ADR 0028](0028-fence-and-taint-untrusted-content.md)).
  It does not restore file-read tracking (the agent must read a file again before editing it), session permission rules, or `/mode`.
- **Secrets are redacted before writing** ([ADR 0031](0031-redact-audit-and-limit.md)), in message text and in tool-call arguments, so a key typed into a message is in memory but not on disk.
  Files are created private (`0600`, folders `0700`) where the OS supports it.
- **A reference to a chat is a number, an id prefix or a word of the title, never a path.** `--resume` and `/resume` can't be made to load an arbitrary file.
- **Fork** copies the log (without the header and titles) into a new file with a header naming its parent. The copy replays to the same conversation and then diverges.
- **Retention**: chats of the project not used for `chat_retention_days` (30) are deleted when a session starts; `save_chats` and `--no-save` turn saving off.
  Neither setting is accepted from a project's own settings file.
- The list reads each file's header and counts message lines without decoding them (`scan`); the title is the last `title` line.

Measured on this machine (Windows, SSD): writing a message costs **2.2 ms** (open, append, close, with redaction); a 1,050-message chat is 1.4 MB (about 1.3 KB a message, mostly the results);
replaying it takes **38 ms**; listing chats costs about 0.7 ms a file once they are in the system's cache, and about **110 ms for the first open of a file written moments before** (the
antivirus scan of a new file, we think: 2.2 s for 20 chats, then 14 ms).

## Consequences
- A resumed chat is the same conversation, including the clearing and summarising that happened, so it fits the window it fitted before.
- The log grows with every result the agent read (1.4 MB per thousand messages): the retention setting is the bound. Results are not stored separately or compressed.
- Listing reads every file in the project. At hundreds of chats a small index file would be better; the format doesn't prevent adding one.
- Two writers to one chat file would interleave their lines. The terminal and the web server must never both have the same chat open: a later lesson makes the server own its chats; there is no lock yet.
- Replay trusts the log: someone who can write to your user folder can put messages into a chat. That folder already holds your audit log, history and trust list, and a message in a log
  is not an approval (approvals are decided at call time).
- A tree (option 4) would make "go back to an earlier message and branch from there" cheap. Ours branches only at the end of a chat (fork); rewinding is the next lessons' subject.
