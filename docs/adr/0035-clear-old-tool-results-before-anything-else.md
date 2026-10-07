# 0035. Clear old results of re-runnable tools when the window fills, before anything else

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
[ADR 0033](0033-estimate-context-and-refuse-overflow.md) made the agent stop instead of sending a conversation that
doesn't fit. That is honest and it ends the task. In a coding agent the thing that fills the window is almost always
**tool results**: whole files, search hits, test output (`/context` shows `tool results` as the largest share after the
fixed tool definitions). And most of them are not needed again once the model has used them.

We measured it with five files of about 2,100 tokens each (2,700 with line numbers) in `qwen3:4b-instruct`'s 8,192-token
window, 3 runs per row (`scripts/micro_lab.py`):

| Task | Clearing | Finished | Code words correct |
|---|---|---|---|
| **work**: read each file, then append its code word to `summary.txt` | off | 0/3 (`context_full` after two reads) | 3/15 |
| | on | **3/3** | **15/15** |
| | on, plus a system-prompt rule to write things down | 3/3 | 15/15 |
| **gather**: read all five, then answer with each file's code word | off | 0/3 | 0/15 |
| | on | 3/3 | **3/15** |
| | on, plus the rule | 3/3 | 3/15 |

Clearing is exactly what a task that *uses* each result needs, and it hurts a task that *collects* results for an answer
at the end: the small model chains `read_file` calls without writing anything down, so by the fifth read the first four
code words exist nowhere. A rule in the system prompt asking it to write down what it needs changed nothing (3/15 both
ways). The final answers were honest ("not available in the result"), not invented.

The cost to the server's prompt cache (`scripts/micro_cost.py`, median of 6 runs, file contents different each run,
two 1,900-token reads in the conversation):

| Next request | Time to read the prompt |
|---|---|
| the same conversation again | 120 ms |
| after the oldest read was replaced by its note | **1,561 ms** |
| with one more 1,900-token read added | 1,916 ms |

Clearing the oldest result changes a message near the start, so everything after it is read again: it costs about as
much as a new result does, once.

## Options
1. **Stop** (status quo): safe and ends the task.
2. **Summarise the conversation with the model**: keeps the gist of everything, but costs a model call that itself has to
   fit, is slow on a 4B model, and can lose or invent details. Needed eventually, and a separate feature.
3. **Drop the oldest messages**: breaks the pairing of a tool call with its result, and loses what the model decided.
4. **Cut every result short up front**: loses information the model needs *now* to protect against needing it *later*.
5. **Replace the oldest results of tools whose output can be got again with a short note**, oldest first, no model call.

## Decision
Option 5, before stopping and before any summary (`harness/context/micro.py`).

- **Which results.** Tools declare `clearable` (fail-closed: default `False`). The built-ins: `read_file`, `grep`, `glob`,
  `list_dir`, `run_shell` and `web_fetch`. `edit_file` and `write_file` results are small and are the record of what changed.
- **When, and how far.** Before a model call, when the estimate is at least 70% of the limit (`warn`). Clear oldest first until the
  conversation is at **half** the limit, so it doesn't run again on the next call: after a clear the next request costs 1.5 s,
  and the 4 or 5 after it cost 0.1 s each.
- **What stays.** The newest `microcompact_keep` (default 2, never below 1) results of clearable tools. If the conversation is still
  `full` afterwards, a second pass keeps only the newest one: with 2,700-token results in a 6,100-token budget, "keep two"
  protects everything (the first version stopped there, and the lab showed it).
- **What the note says.** The call (`read_file(path='x.py')`), its size in tokens and lines, and how to get it back. **None of the
  result's words**: the result may have been untrusted content, the note is not inside the `<untrusted>` fence, and a preview
  of 100 characters would have carried an injection past [ADR 0028](0028-fence-and-taint-untrusted-content.md). The taint
  state lives in the permissions, not in the messages, so clearing a page does not make the chat trusted again.
- **No history is removed.** Each cleared result stays in its place with the same call id and tool name; only the text changes.
- **It is visible.** A `microcompact` event, a line in the terminal, `/context`, and an audit entry naming the tools and
  tokens. Setting `microcompact` (default on) turns it off, `microcompact_keep` changes the protection.

## Consequences
- Tasks that act on each result as they go (read, edit, test) now run past the window. Tasks that collect from many sources can
  lose what was collected; the user guide says so and suggests writing findings to a file. Compaction (summarising) is the answer
  for those, and clearing remains the cheap first step in front of it.
- Every clear costs one cold read of what follows it (here 1.6 s), which is why it clears down to half and not just under the line.
- A model that doesn't act on a note will answer from what it has. We saw "not available in the result" and no invented
  values; if a model starts guessing instead, the setting is the fix, and a rule in the prompt did not help at this size.
- `clearable` is a new flag every new tool must consider: a tool whose result can't be reproduced (asking the user, a sub-agent's
  report) leaves it `False`.
