# 0056. The harness offers a plan the model wrote as its answer, and accepting it carries the plan out

- **Status:** Accepted
- **Date:** 2026-10-13
- **Amends:** [ADR 0043](0043-plan-mode-ends-with-the-users-yes.md) (the choices, and a second way to propose)

## Context
ADR 0043 made plan mode end only with the user's yes, through `exit_plan_mode`, a tool that exists only in plan mode. Its own measurement
was that `qwen3:4b-instruct` never called it (0 of 5 runs). It wrote its plan, or its next step, as its answer and stopped. Trying v0.8.0,
the user hit exactly that: a plan, no options, and the mode to change by hand ("the user has to manually change the file"). They asked
for **revise** and **accept and implement**.

The course has met this shape three times (the todo list, ADR 0042; the journal, ADR 0040; tool search, ADR 0048): a small model doesn't
call the tool meant for it, so the harness does the step from what it can see. Here it can see that a plan-mode request ended with an
answer shaped like a plan.

## Options
1. **Stronger words in `PLAN_RULE`** ("you MUST call exit_plan_mode"). Lesson 45 had already said "do not write the plan as your answer",
   and it did nothing.
2. **Force the tool** (`tool_choice` for the last step). Not every provider supports it, and it would make the model call the tool at the
   first step, before it has read anything.
3. **The harness offers the answer as the plan**, with the same choices and the same rule that only the user's answer changes the mode.
4. As 3, and accepting **also sends the request that carries the plan out**, so "accept" doesn't end in a prompt waiting for "go ahead".

## Decision
Option 4.

- **When**: `Session.after_plan(answer)` runs after every request (`cli.run_turn`, shared by the terminal and the web page). It offers the
  answer when the mode is still `plan`, the request completed (not stopped, not out of steps, not failed), `exit_plan_mode` wasn't used
  in this request, and the answer looks like a plan: two or more numbered steps, or at least 200 characters (`looks_like_plan`).
- **The choices**, the same for both ways in (`CHOICES`, `plan_choice`):
  - `y` **Accept and implement**, asking before each change: the mode becomes `default`;
  - `a` **Accept and implement**, accepting file edits: the mode becomes `accept-edits`;
  - `e` **Edit the plan myself**: only where the interface's `ask_text` can start from a text (the web page: a box with the plan in it).
    The edited plan is shown again and the question asked again;
  - `r` **Revise**: the user's words go back to the model, still in plan mode;
  - `k` **Keep planning**: nothing.

  `n` and `f` of ADR 0043 became `k` and `r`, to match the words. Accepting saves the plan and makes its steps the todo list, as before
  (`approve_plan`).
- **Accepting carries it out.** `after_plan` returns the next request: `IMPLEMENT` ("Your plan is approved. Carry it out now, step by step,
  and say what you did when you are done."), or the edited plan with "I edited your plan. Carry out this version now". `run_turn` runs it at
  once. The terminal prints it; the web page shows it as the user's message (`WebUI.request`, a `user` event). For `exit_plan_mode` the
  approval is the tool's result, and the model goes on in the same request, as before.
- `PLAN_RULE` now says "give your plan, with exit_plan_mode or as your answer". The tool stays.

Measured with `scripts/plan_lab.py` (the six-part request of ADR 0042, `qwen3:4b-instruct`, a scripted user who accepts with file edits,
5 runs):

| run | plan given with `exit_plan_mode` | offered by the harness | files changed before approval | refused calls (mean) | parts done (of 6, mean) | all six |
|---|---|---|---|---|---|---|
| v0.8.0 | 0/5 | (not offered) | 0 | 0.8 | 0.0 | 0/5 |
| now | 3/5 | 2/5 | **0** | 1.2 | **3.8** | **2/5** |

Every run now ends with the choices (5 of 5, before 0), and accepting carries the plan out. The new `PLAN_RULE` wording ("with
exit_plan_mode or as your answer") also made the model call the tool itself in 3 of 5 runs, where the stricter Lesson 45 wording got 0.
In one of the two offered runs the answer was a statement of intent rather than a plan ("I'll now proceed with the first task ..."); it was
accepted and the model then did none of the six parts. Plan mode itself held in every run: nothing changed before the approval.

## Consequences
- With a small model plan mode now works end to end: look, plan, choose, done, with no mode to change and nothing to retype.
- The safety of ADR 0043 is unchanged: the permission layer refuses every change in plan mode, the model has no way to leave it, and only
  the user's key changes the mode. The untrusted-content warning comes before either way of offering.
- An answer that isn't a plan can be offered as one: a long report on what the agent read is over 200 characters. Choosing **Keep
  planning** costs one keypress. A stricter test (steps that name files) would miss plans that are prose.
- The follow-up request is the harness's words in the user's place. It is shown as such in both interfaces, saved in the chat, and
  undone by `/rewind` like any request.
