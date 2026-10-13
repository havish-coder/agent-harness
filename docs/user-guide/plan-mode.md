# Plan mode

For a change you want to approve **before** anything happens, tell the agent to plan first. In plan mode it can read, search and think, but **nothing that changes anything runs**. When it knows what to do, it shows you a plan, and
only your answer lets it start.

```text
> /plan add a "usage" section to the README and a test for quantity 0
plan mode on: the agent can read but not change anything, and will propose a plan for you to approve. /plan off leaves it.

● read_file(path='project/README.md')
● read_file(path='project/tests/test_cart.py')

┌ Proposed plan ───────────────────────────────────────────────────────┐
│ Goal: document Cart and test the quantity-0 case.                     │
│ 1. Edit project/README.md: add a "## Usage" section with a Cart example│
│ 2. Edit project/tests/test_cart.py: add test_zero_quantity_raises()   │
│ 3. Run the tests: cd project && python -m pytest -q                  │
│ Unsure: whether quantity 0 should raise ValueError or be ignored.     │
└──────────────────────────────────────────────────────────────────────┘
What should happen with this plan?
  [y] Accept and implement (ask before each change) / [a] Accept and implement (accept file edits) / [r] Revise: I'll say what to change / [k] Keep planning:
```

The agent can hand you its plan two ways: with the `exit_plan_mode` tool, or simply as its answer. Either way you get the
same choices. (Small models almost always write the plan as their answer; before v0.9 that left you to switch modes and ask
again by hand.)

## Turning it on
- `/plan` turns plan mode on. `/plan some task` turns it on **and** sends the task.
- `harness --mode plan` starts in it. `/mode plan` is the same as `/plan`.
- `/plan off` leaves it, back to the mode you were in. `/plan show` shows the last plan (this session's, or the newest saved one).

## What you answer
| | |
|---|---|
| `y` **Accept and implement** (ask before each change) | the mode becomes **default** and the agent starts at once: each change still asks you |
| `a` **Accept and implement** (accept file edits) | the mode becomes **accept-edits** and the agent starts at once: file edits in the workspace run without asking; commands still ask |
| `e` **Edit the plan myself** | in the [web UI](web-ui.md) only: a box opens with the plan in it; change any step, send it, and choose again. The agent carries out *your* version |
| `r` **Revise** | stay in plan mode and type what to change: the agent gets your words and proposes again |
| `k` **Keep planning** (or Enter) | stay in plan mode: nothing changed |

When you accept a plan the agent wrote as its answer, the harness sends the next request for you (*"Your plan is approved.
Carry it out now, step by step"*), so you don't have to. In the web UI it appears as your message.

An approved plan is **saved** in your user folder (not in your project): `projects/<project>/plans/<time>-<title>.md`. Its **numbered steps become the agent's [todo list](todo.md)**, with the first one in progress, so the agent
has the checklist without being asked to write it a second time.

## What makes it safe
- **The block is the permission layer's, not a request in a prompt.** In plan mode every tool that changes something is refused, however the model was talked into trying: file edits, commands that aren't clearly read-only, anything.
  The refusal says "plan mode is on" so the model describes the change instead.
- **Only your answer changes the mode.** `exit_plan_mode` only shows the plan and asks you, and a plan written as an answer is offered by
  the harness; either way the harness switches the mode when you say yes. The model has no tool that leaves plan mode by itself. And the
  tool is only offered while plan mode is on.
- **If the chat has read content you may not trust** (a web page, a file from a stranger), the question comes with a warning to read each step: a plan is a good place for a hostile page to hide a step.
- Your answer, and the size of the plan, go in the [audit log](audit-and-limits.md); the plan's text doesn't.

## What it measured
With `qwen3:4b-instruct` and a request with six parts (`scripts/plan_lab.py`, 5 runs, accepted with file edits):

| | v0.8.0 | v0.9 |
|---|---|---|
| plan given with `exit_plan_mode` | 0/5 | 3/5 |
| plan written as the answer, offered by the harness | (not offered) | 2/5 |
| **ended with your choices** | **0/5** | **5/5** |
| files changed before an approval | **0** | **0** |
| parts done (of 6, mean) | 0.0 | 3.8 |
| all six | 0/5 | 2/5 |

Plan mode held every time: **no file changed** before an approval, and the changes the model tried anyway were refused. Since v0.9
every run ends with the choices, whichever way the model gave its plan, and accepting carries it out. A small model may still offer a
statement of intent ("I'll now proceed with ...") instead of a plan; read what you accept, and choose **Revise** or **Keep planning** when it
isn't a plan.

## Limits
- A plan is only as good as what the agent read before writing it, and nothing checks that the agent then follows it (the todo list and your approvals for each change are the checks).
- Plan mode doesn't make a read-only command safe to run from a page's instruction: the usual rules still apply to everything the agent reads. See [untrusted content](untrusted-content.md).
