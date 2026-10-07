# 0034. Build the system prompt from sections ordered by how often they change, within a budget

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
The system prompt began as one string with a placeholder for the workspace listing, plus two appendages
(the untrusted-content rule, the output style). It is about to gain more parts: facts about the environment
(date, system, shell, git), project memory, a project journal. Three problems follow from leaving it a string:

- **Nothing says which part may change.** Model servers keep the computed state of the start of the last
  prompt and reuse it up to the first token that differs (the *prefix cache*). A line that changes every
  session placed early makes everything after it be read again.
- **Nothing bounds it.** A workspace with thousands of files, or a long memory file, could take the window the
  conversation needs ([ADR 0033](0033-estimate-context-and-refuse-overflow.md)), and `/context` would show a
  number but no way to see which part to blame.
- **Nothing says what was left out.** The listing was already capped at 50 lines without telling anyone.

We measured the cache on `qwen3:4b-instruct` with Ollama (RTX 3050, 8 runs per row, the real system prompt and
the real tool definitions, `scripts/prefix_cache.py`):

| What changed between two requests | Median time to read the prompt |
|---|---|
| only the user's question | **249 ms** |
| the date line, which comes **last** in the system prompt | 1,117 ms |
| the date line, which comes **first** in the system prompt | 1,318 ms |

The server reports `prompt_eval_count` = 1,676 for all of them, so the count cannot show the cache; only the
time does. And the order helps less than the theory suggests: qwen3's chat template puts the **tool
definitions after the system text** (about 1,400 of the 1,676 tokens), so any change inside the system text
makes the server read the tools again. Ordering only saves what comes *before* the change (the role and the
rules, about 140 tokens: a 15% difference here). What matters more is that **nothing changes between turns**:
then each turn costs about a quarter of a second, a fifth of the cost of a changed prompt. (One of the eight
"date last" runs took 235 ms: the server kept more than expected. Medians are given for that reason.)

## Options
1. **Keep one string.** Simple, and each new feature adds another `+=`.
2. **A template file with placeholders.** Readable, but order and size are still implicit.
3. **Named sections with a stability and a budget** assembled by one function, with a record of what each cost
   and what was shrunk or dropped.

## Decision
Option 3 (`harness/context/prompt.py`).

- A `Section` has a name, text, a **stability** (0 never changes, 1 changes with a setting or `/style`, 2 fixed
  for a session), whether it is **required**, and optionally a **shrink** function that returns a smaller
  version for a token target (the workspace listing).
- `assemble()` joins the sections **most stable first** (stable sort: the order given is kept within a stability),
  so the same inputs always give the same bytes.
- The prompt has a **budget**: a quarter of the context window, at least 600 tokens. Over it, the most volatile
  section that can shrink is shrunk (the listing; asked again for less if its first answer is not smaller),
  then optional sections are dropped, most volatile first. Required sections (the role, the untrusted-content
  rule) are never dropped; if they alone are over budget the overshoot is reported.
- Every part's cost and any "shrunk from N" / "dropped" note is kept, and `/prompt` shows them.
- The **environment** section states what the model cannot know: the date, the system, the shell that
  `run_shell` uses, and a one-line git summary (branch, number of changed files), taken at session start.
- Changing the output style rebuilds the prompt; the sections before the style stay byte-identical.
- `SYSTEM_PROMPT` stays as the one-string form for scripts and recorded sessions.

## Consequences
- Memory (Lesson 41) and the journal (Lesson 42b) are new sections, not new string appends, and they inherit
  the budget and the report.
- A prompt that changes **during** a session (a style switch, trusting a folder) costs about a second on Ollama
  the next turn, because the tool definitions are read again. On cloud APIs that put tools before the system
  prompt, the cost is only what comes after the change. Do not put anything that changes every turn in the
  system prompt: that belongs in a message.
- The budget is an estimate ([ADR 0033](0033-estimate-context-and-refuse-overflow.md)); the git summary and the
  date are captured once, so the model may be a few edits behind. The text says "at session start".
- With a 4,096-token window the budget is 1,024 tokens: the role and rules take about 140, the environment
  about 50, and the listing is shrunk to the rest.
