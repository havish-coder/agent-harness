# 0026. Decide every tool call with modes and allow/ask/deny rules, strictest first

- **Status:** Accepted (amends [0005](0005-approve-every-non-read-only-call.md))
- **Date:** 2026-10-06

## Context
Since v0.2 every call that isn't read-only asks (ADR 0005), and `--yes` turns all questions off.
That leaves two bad choices. Asking for everything trains the user to press `y` without reading
(approval fatigue, T12 in the [threat model](../security.md)). Asking for nothing means one
injected instruction can write a git hook or run `curl -d @.env` (T4, T8). The attack lab
(Lesson 27) showed that with `--yes` every attack that gets past the path jail succeeds.

Users need finer control: "tests can always run", "never push", "edits are fine for this task,
commands still ask", "just look, don't touch". Some places are dangerous to write to whatever
the user has chosen, because something runs their contents later (`.git/hooks`, CI workflows,
our own `.harness/settings.json`).

The decision must be deterministic code ([ADR 0024](0024-deterministic-security-decisions.md)):
the same call in the same state always gets the same answer, and the model has no say in it.

## Options
1. **Keep yes/no per call, plus `--yes`.** Simple; doesn't solve fatigue or offer a middle ground.
2. **Allow lists only** (anything not listed asks). No way to forbid something absolutely, or to
   keep a few things asking inside a broad allow.
3. **Modes plus three kinds of rules, combined by a fixed precedence**, with a short list of
   protected paths that always ask.
4. **Risk scoring** (a classifier, possibly a model, rates each call). Flexible, but not
   predictable, hard to test, and open to the same injection it is meant to catch.

## Decision
Option 3. `Permissions.decide(call, tool)` in `harness/security/permissions.py` returns
`allow`, `ask` or `deny` with a reason, in this order, where an earlier, stricter answer can't be
overruled by a later one:

1. a matching **deny** rule → deny;
2. a write to a **protected path**, or a matching **ask** rule → ask;
3. the **mode**: `plan` denies anything not read-only; `bypass` allows; `accept-edits` allows
   file-tool changes;
4. a matching **allow** rule → allow;
5. read-only → allow;
6. otherwise → ask.

Details:
- **Rule syntax** `tool` or `tool(pattern)`. Each tool declares its *subject* (`path` for file
  tools, `command` for `run_shell`), inferred from its parameters by the `@tool` decorator. Path
  patterns are globs on the **resolved**, workspace-relative path (`*` within one folder, `**`
  across folders, a bare folder name covers its contents; case-insensitive on Windows). Command
  patterns are globs on the whole command text, `*` matching spaces.
- **"Always"** answers add a session rule the decision suggests: the exact command for
  `run_shell` (matched literally, so a `*` in `rm *.pyc` is not a wildcard), the whole tool for
  file tools. Protected paths offer no "always".
- **Sources.** Rules add up across settings layers, each keeping its source for display. Project
  settings may add `ask` and `deny` rules but not `allow` rules or a mode.
- **Refusals tell the model why** and not to work around it; denied and refused calls are
  separate events (`tool_denied` vs `tool_refused`).
- **Threading.** Calls are checked and decided on the loop's thread before any of a batch runs,
  so questions and events never come from worker threads.
- `--yes` became `--mode bypass`.

## Consequences
- Routine work stops asking (`allow` rules, `accept-edits`), risky work keeps asking (`ask`,
  protected paths), and some things can be ruled out entirely (`deny`), also in bypass mode.
- The attack lab now runs in bypass mode with a user who answers "no": T4 through the file tools
  is closed in the worst case.
- **Known gap:** command rules see the whole command, so `run_shell(pytest*)` also matches
  `pytest; curl ...`. Matching each part of compound commands, and removing secrets from the
  command environment, is the next step (T6, T7). A shell command can still write into
  protected folders; only an OS sandbox closes that fully.
- Approvers take an optional `decision` argument and may return `"always"`; old
  `(call, tool) -> bool` approvers keep working.
- The precedence is part of the user-visible contract (documented in the
  [permissions guide](../user-guide/permissions.md)); changing it later is a breaking change.
