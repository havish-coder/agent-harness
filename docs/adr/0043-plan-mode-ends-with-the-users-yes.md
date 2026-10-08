# 0043. Plan mode ends only with the user's yes, through a tool that exists only in plan mode

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
Permission mode `plan` ([ADR 0026](0026-permission-modes-and-rules.md)) already makes everything that changes something refuse, so an agent in it can look but not touch. What it lacked was the way out: a model that has finished looking has
nowhere to put its plan except its answer, nothing for the user to approve, and no step that connects "the plan is fine" to "now make the changes". Users resorted to `/mode default` and retyping the request.

The measurements that bear on the design (`scripts/plan_lab.py`, `qwen3:4b-instruct`, the six-part request of ADR 0042, PL_RUNS runs per row):

PL_TABLE

## Options
1. **Leave it to the user**: plan mode stays a mode; the user reads the answer and switches mode by hand.
2. **A tool the model calls to leave plan mode itself** ("I'm done planning, switch to default"). One call; no question. The model decides.
3. **A tool that proposes, and the user decides** (`exit_plan_mode(plan)`): the plan is shown, the user answers, the harness switches the mode.
4. As 3, plus the harness acts on the approval (saves the plan, starts the todo list from its steps).

## Decision
Option 4 (`harness/plan.py`, `Session.review_plan`).

- **The refusal stays where it was**: the permission layer denies every change in plan mode (a hook, a rule or a persuaded model changes nothing). The plan tool adds a way out, not a way around.
- **Only the user's answer changes the mode.** `exit_plan_mode` is read-only for permissions (so plan mode allows it), and its body shows the plan and asks. `y` makes the mode `default`, `a` `accept-edits`, `n` and Enter leave it, `f` leaves it and asks for the words.
  Option 2 was rejected because it makes the *model's* statement ("I have a plan") the thing that lifts a safety restriction.
- **The tool exists only in plan mode**, through a new `Tool.enabled` switch checked every time the schemas are built: outside plan mode the model isn't told about it, and a call to it is an error that lists what is available.
  The switch is general (the tool-search lesson uses it too) and fails closed: a broken switch hides the tool.
- **The prompt says so** while plan mode is on (`PLAN_RULE`, a section that appears and disappears as the mode does; the system prompt is rebuilt then, which costs one re-read of the prompt by the server).
  It tells the model to propose with the tool and not to write the plan as an answer. PL_RULE
- **If untrusted content was read**, the question is preceded by a warning: a plan is a convenient place for a hostile page to hide a step. Approval in `accept-edits` mode doesn't loosen the taint rule: after untrusted reading, edits still ask.
- **An approved plan is saved** in the user's folder (`plans/`, not in the project), its numbered steps become the todo list ([ADR 0042](0042-a-todo-list-the-harness-can-see.md)) with the first in progress, and the audit log records the answer and the plan's size.
- `/plan [TASK|show|off]`: turn it on (and send TASK), show the last plan, leave. A local command can now return `Send(text)`: do my thing, *and* send this to the agent.

## Consequences
- The user gets one place to say yes, with the mode they want afterwards, and the agent gets a checklist it didn't have to write twice.
- A model that never calls `exit_plan_mode` (it writes the plan as its answer) leaves the user to read it and say "go ahead" in words; they can then `/plan off`. PL_CONSEQ
- Approving a plan doesn't verify that the agent then follows it. What the agent does next is decided by the permission rules, and by the user's answers to each change in `default` mode.
- In an interface that can't ask, the plan can't be approved: the tool answers with an error and tells the model to describe the plan instead.
