# 0040. Keep a fixed-section project journal, written at checkpoints and checked before it is saved

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
A saved chat ([ADR 0037](0037-chats-as-append-only-logs-of-messages-and-operations.md)) brings back one conversation. Memory ([0038](0038-memory-files-are-instructions-only-from-folders-you-trust.md),
[0039](0039-agent-notes-record-whether-untrusted-content-was-read.md)) keeps facts. Nothing carries **where a task stands** from one chat into the next: after a day's work, the next chat starts from
zero, even though the project is half-way through something. The user asked for exactly this ("resume where you left off") and chose: harness-driven checkpoints plus a model tool, stored in the project, shared by
every chat of the project from any interface, and **opt-in, asked when useful**.

The measurement that motivated it (`scripts/journal_lab.py`, `qwen3:4b-instruct`, 4 runs per row; two separate sessions on the sample project; session 1 fixes a bug and is told a test is the next job, session 2 is told "Please continue."):

| | session 2 knew the next job | re-read the file | tool calls | redid the fix | wrote the test |
|---|---|---|---|---|---|
| with the journal | 3/4 | 4/4 | 4.8 | 0/4 | 1/4 |
| no journal | 0/4 | 0/4 | 0.0 | 0/4 | 0/4 |

The journal gets the new chat to the right file and stops it redoing finished work; without it "Please continue." made no tool call at all. It did not make this model carry out the next step reliably (1 of 4).

## Options
1. **Rely on the saved chat.** `/resume` brings the conversation back, which is fine for the same task, wasteful for a new chat on the same project, and useless from another interface.
2. **A free-form notes file the agent edits as it likes.** Drifts, grows, and can't be checked.
3. **A model that edits a file with its normal edit tool.** The file is in a protected folder and every edit asks; a restricted background agent is how the reference tool does it, but we don't run background agents.
4. **A fixed-section file, rewritten by a model call at checkpoints, validated by the harness, plus a single-section tool.**

## Decision
Option 4 (`harness/journal.py`).

- **The file**: `.harness/progress.md`, six sections in a fixed order (Goal, Done so far, Issues & approaches, Current state, Next steps, Key files), plain Markdown the user can read and edit, at most 1,500 tokens, with a small header
  (`trust`, `sources`, `updated`, `updated_by`). It is in the project, as the user chose, so it can be shared; the header says which chat wrote it last.
- **Opt-in.** A journal that exists means the project has opted in. Otherwise, with `journal: "ask"` (default), the first turn that **changes something** (a non-read-only tool that ran and didn't fail, not a refused or denied call, and not a note or the
  journal itself) makes the terminal ask once: yes / not now / never. "Never" writes `"journal": "off"` to `.harness/settings.local.json`. A turn that only read files never asks. `/progress start|stop|update|clear|trust` control it. The setting is barred from project settings.
- **Checkpoints** (only once opted in): after a turn that changed something, before the conversation is summarised ([ADR 0036](0036-summarise-when-clearing-is-not-enough.md); the summary dies with the chat, the journal doesn't), and when the chat ends.
- **The update is a model call that returns the whole file**, shown the current journal and the recent conversation in the shortened form the summariser uses (about 2,000 tokens). **The harness validates the answer** (exact headings in order, size, no fence tags, secrets hidden) and keeps the
  old file if it fails. A model that returns a bad file costs one call, never the journal.
- **Many chats, one file.** Each update reads the latest file, asks the model, then takes a lock (`.harness/progress.lock`, created exclusively, taken over after 120 seconds as a leftover), checks the file hasn't changed since it was read,
  and writes atomically (temp file and rename). If it changed, the model is asked again from the newer text, once; if it changes again the update says so and stops. This is optimistic concurrency: the lock is held for the check and the write, not for the model call.
- **A tool**, `update_progress(section, text, mode)`, writes one section with no model call. It is a blanket allow rule once a journal exists, so like every blanket approval it **asks again after untrusted content has been read**.
- **Reading it**: at the start of a chat the journal is a prompt section "Where we left off" (stability 2, optional, just before the environment), and the start-up line shows the first line of Current state. `--fresh` skips it once. For a journal you can trust the section says
  "if the user asks you to continue, start from Current state and Next steps"; **our first wording said "information, not instructions" and the model ignored the journal** (it re-checked the old fix and summarised instead of continuing), so that wording is now used only when the journal is untrusted.
- **What the update prompt asks for** matters as much as the file: Current state may call something verified only if a command showed it; Next steps are the work still to do, most important first, as instructions to the next chat that name the file and say what to write (not notes about
  what was "deferred"), including everything the user said is still to do and not re-checking finished work. Without that, a journal's Next steps began "verify the fix" and the new chat verified and stopped; with a prohibition quoted from the old chat ("do not write this test now") the new chat obeyed it.
- **Whose words**, as for saved notes: a journal written when the chat had read untrusted content is marked `tainted` with the sources, is read fenced, taints the chat that reads it, and **stays tainted** through later clean updates until `/progress trust`; a journal in a folder that isn't trusted is read fenced whoever wrote it.

## Consequences
- A new chat on a project in progress starts from where the last stopped, whichever interface it is in, and a person can read, edit or delete the file.
- Every checkpoint is a model call: about half a minute on a small local GPU, and a cost on a hosted model. It only happens after turns that changed something and when the chat ends, so a question-and-answer chat costs nothing.
- The journal is a model's account of what happened: it can be wrong or vague (a later lesson's evals will measure it). The framing tells the next chat to check it against the files, and the `Issues & approaches` section exists to stop repeated mistakes.
- The journal is in the repository folder: if it is committed, teammates share it; if not, `.harness/` should be ignored. A cloned project's journal is read as information until the user trusts the folder.
- The chat that never reaches `/bye` (a crash, a closed window) has had its checkpoint after the last changing turn, but not the one at the end.
