# 0042. Give the agent a todo list the harness can see, and send it back when it tries to finish early

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
A small model asked for a job with several parts does the first, says it is finished, and stops. Measured (`scripts/todo_lab.py`, `qwen3:4b-instruct`, a request with six checkable parts, TL_RUNS runs per row):

TL_TABLE

The model can't be relied on to track a task it only holds in its head. Two things can help: write the plan where the model will see it again on every call, and let the harness (which can read the list) notice that the model is finishing with work open.

## Options
1. **Do nothing**: rely on the model to finish what it was asked.
2. **A tool the model calls** (`todo_write`, whole list each time) and nothing else.
3. **The tool, plus a sentence in the system prompt** saying when to use it.
4. **The tool, the sentence, and a harness check at the end of the request**: if items are open, add a note and let the model carry on (at most twice).
5. **The harness writes the list itself** from the user's numbered request.

## Decision
Option 4 (`harness/todo.py`), with these choices:

- **The whole list, replaced each time**, not "add item / mark item". The latest call *is* the state, so it can always be **rebuilt from the conversation** (resume, fork, rewind need nothing stored beside the chat log), and the model can't get out of step with the harness.
  Cost: a small model resends every item each time. The lab's lists were short; the limit is 20 items of 120 characters.
- **Forgiving about form**: plain strings are pending items, `done`/`in progress`/`todo` and similar are understood, other names for the text (`task`, `title`) are accepted, two items in progress become one with a note, and `content` is cleaned of control characters
  (it is shown in a terminal). Everything else is an error that says how to fix it.
- **Read-only for permissions**: it changes nothing outside the harness, so it never asks and works in plan mode.
- **A sentence in the system prompt** (`TODO_RULE`). TL_RULE
- **The harness writes the list from a numbered request** (`seed_todos`, `Agent.on_request`): three or more numbered lines at the left margin, each cut to 120 characters, become the list with the first item in progress, and a note appended to the request tells the model. It is the user's own list, so it is not marked
  as written after untrusted reading. It is not done while a list with open items is in progress. TL_SEED_NOTE
- **The nudge** is a note from the harness in the user role ("your todo list still has unfinished items: ..."), at most **twice per request** (`MAX_NUDGES`, enforced by the loop, not by the check), and **never after the user refused a call** in that request, nor when the answer was cut off or the request stopped for any other reason.
  TL_NUDGE
- **Whose words**: a list written after untrusted content was read is marked; when the harness quotes it back (in a nudge, or in a summary) it is fenced as information. Items are the model's own notes; a nudge repeating an injected instruction in the user role would
  lend it more authority than it has. What the model then does is still decided by the permission rules.
- **A summary repeats the list** word for word (`Agent.carry`), so compaction can't lose or reword it.
- Not stored anywhere else: `/todo` shows it, `/todo clear` empties it, a finished list disappears at the next request, `/reset` empties it.

Setting `todo` (default on, a project may set it); event `todos` (the list as data, for the web UI) and `nudge`.

## Consequences
- A model that never calls the tool gets no help from it: the rule in the prompt, not the tool's description, is what makes it write a list. TL_CONSEQ
- The nudge costs a model call per time it fires, and can't force completion: a model that ignores two nudges finishes with items open, and says so.
- Nothing stops a model from marking items completed that it didn't do. The list is a reminder, not a verifier; checking the result is the job of tests, hooks and evals (Lesson 58).
- A harness that wrote the list itself (option 5) would not depend on the model's compliance, but would guess at structure in the user's text. It is the next thing to try if the model still ignores the tool.
