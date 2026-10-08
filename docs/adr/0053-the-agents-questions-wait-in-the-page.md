# 0053. The agent's questions wait in the page: one at a time, the first answer counts, Stop answers no

- **Status:** Accepted
- **Date:** 2026-10-08

## Context
In the terminal, the agent's thread asks and the same thread reads the keyboard: `input()` blocks until you answer. Four things ask:
the approver (may this call run?, ADR 0026), `ask_user` (ADR 0044), plan review (ADR 0043) and the journal's offer (ADR 0040). Until
now the web session had no approver, so every call that would ask was refused (fail-closed, ADR 0051), and the other three weren't
offered at all.

In the browser the question has to travel to a page and the answer back, from any of the tabs that are open, or from none.

## Options
1. **Refuse what would ask** (as before): safe, but the web UI can't edit or run anything you haven't allowed in advance.
2. **Answer from the page, with a timeout**: after N minutes without an answer, refuse. A long lunch would turn into a "no" the agent then
   works around.
3. **Answer from the page, wait as long as it takes**: the worker thread waits; a page answers, or Stop cancels.

## Decision
Option 3 (`harness/web/server.py`: `Question`, `WebUI.ask`, `WebUI.reply`, `WebUI.cancel`, `WebApprover`, `check_answer`).

- **The same questions as the terminal.** `WebApprover` sends what the terminal approver prints: the tool, its arguments, the diff
  (`tool.preview`, up to 20,000 characters), the command for `run_shell`, why it asks, the risks the permissions found, whether the call
  may destroy data, and what "always" would allow when the permissions offer a rule. Answers: `yes`, `no`, `always` (only if offered).
  `ask_choice` and `ask_text` carry `ask_user`, plan review and the journal's offer; `show_plan` sends the plan.
- **One at a time.** The agent's thread asks; nothing else does, so there is at most one question. It is an event (`question`, with an
  id) for every open page, and part of `/api/state` for a page that opens later.
- **The first answer counts.** `POST /api/answer {id, answer}` is checked against the question (the page is trusted no more than a
  form: an option that wasn't offered, `always` when it wasn't, text over 4,000 characters, are refused with 400). A second answer, from
  another tab or a double click, gets 409. Every page is told (`answered`), without repeating typed text.
- **No timeout.** The question waits. **Stop** answers it with its safe default (`no`, or nothing) and stops the request, which is rolled
  back as usual.
- With an approver, the web session offers `ask_user` as the terminal does.

## Consequences
- The web UI can do everything the terminal can, under the same permissions: what runs without asking, what asks and what is refused
  are decided by the same code; only where the question is shown changed.
- Measured (scripted model, in-process page): a question reaches the page 0.42 ms after it is asked; from the click to the tool's result
  in the page, 5 ms (median of 20).
- A question asked while no page is open waits until one is opened (the server prints nothing about it).
- Not done (YAGNI): editing the call before approving it (the reference's permission requests can carry changed input), notifications
  outside the browser tab (the tab's title changes while the agent waits).
