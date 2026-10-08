# Plan mode

For a change you want to approve **before** anything happens, tell the agent to plan first. In plan mode it can read, search and think, but **nothing that changes anything runs**. When it knows what to do, it shows you a plan, and
only your answer lets it start.

```text
> /plan add a "usage" section to the README and a test for quantity 0
plan mode on: the agent can read but not change anything, and will propose a plan for you to approve. /plan off leaves it.

● read_file(path='project/README.md')
● read_file(path='project/tests/test_cart.py')
● exit_plan_mode(plan='...')

┌ Proposed plan ───────────────────────────────────────────────────────┐
│ Goal: document Cart and test the quantity-0 case.                     │
│ 1. Edit project/README.md: add a "## Usage" section with a Cart example│
│ 2. Edit project/tests/test_cart.py: add test_zero_quantity_raises()   │
│ 3. Run the tests: cd project && python -m pytest -q                  │
│ Unsure: whether quantity 0 should raise ValueError or be ignored.     │
└──────────────────────────────────────────────────────────────────────┘
Go ahead with this plan?
  [y] yes, ask me before each change / [a] yes, and accept file edits / [n] no, keep planning / [f] no, I'll say what to change:
```

## Turning it on
- `/plan` turns plan mode on. `/plan some task` turns it on **and** sends the task.
- `harness --mode plan` starts in it. `/mode plan` is the same as `/plan`.
- `/plan off` leaves it, back to the mode you were in. `/plan show` shows the last plan (this session's, or the newest saved one).

## What you answer
| | |
|---|---|
| `y` | start; the mode becomes **default** (each change still asks you) |
| `a` | start; the mode becomes **accept-edits** (file edits in the workspace run without asking; commands still ask) |
| `n` (or Enter) | stay in plan mode: nothing changed, the agent is told you did not approve |
| `f` | stay in plan mode, and type what to change: the agent gets your words and proposes again |

An approved plan is **saved** in your user folder (not in your project): `projects/<project>/plans/<time>-<title>.md`. Its **numbered steps become the agent's [todo list](todo.md)**, with the first one in progress, so the agent
has the checklist without being asked to write it a second time.

## What makes it safe
- **The block is the permission layer's, not a request in a prompt.** In plan mode every tool that changes something is refused, however the model was talked into trying: file edits, commands that aren't clearly read-only, anything.
  The refusal says "plan mode is on" so the model describes the change instead.
- **Only your answer changes the mode.** `exit_plan_mode` only shows the plan and asks you; the harness switches the mode when you say yes. The model has no tool that leaves plan mode by itself. And the tool is only offered while
  plan mode is on.
- **If the chat has read content you may not trust** (a web page, a file from a stranger), the question comes with a warning to read each step: a plan is a good place for a hostile page to hide a step.
- Your answer, and the size of the plan, go in the [audit log](audit-and-limits.md); the plan's text doesn't.

## What it measured
With `qwen3:4b-instruct` and a request with six parts (`scripts/plan_lab.py`, 5 runs):

| run | plan proposed with `exit_plan_mode` | refused calls (mean) | files changed before an approval | parts done (of 6, mean) | all six | tool calls (mean) |
|---|---|---|---|---|---|---|
| no plan mode (bypass, for comparison) | 0/5 | 0.0 | (not measured) | 3.2 | 1/5 | 5.6 |
| plan mode | **0/5** | 0.8 | **0** | 0.0 | 0/5 | 8.6 |

Plan mode held every time: **no file changed** before an approval, and the attempts the model made anyway (0.8 per run) were refused. But this small model **never proposed its plan with `exit_plan_mode`**: it wrote its next step as an answer ("I'll now work on the fix ...") and stopped. With such a model, read the answer, then `/plan off` and ask it to go ahead. Larger models are more likely to use the tool.

## Limits
- A plan is only as good as what the agent read before writing it, and nothing checks that the agent then follows it (the todo list and your approvals for each change are the checks).
- Plan mode doesn't make a read-only command safe to run from a page's instruction: the usual rules still apply to everything the agent reads. See [untrusted content](untrusted-content.md).
