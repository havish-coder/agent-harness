# 0024. Make security decisions in deterministic code; treat tool calls as untrusted input

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Until v0.4 the only protection is approval: every tool call that isn't read-only asks first.
That is safe but noisy, and noisy prompts get approved without reading. v0.5 adds automatic
decisions (permission modes, allow rules, read-only command detection), so something other
than the user now decides whether a call runs.

The calls being decided come from a model that can be wrong and can be steered by text it read
(prompt injection). Whatever decides must not be steerable by the same text.

## Options
1. **Keep asking for everything.** Safe on paper; in practice approval fatigue makes it unsafe.
2. **Ask a model whether a call is safe** (a classifier). Handles fuzzy cases, but it reads the
   same attacker-controlled text, gives different answers to the same input, costs a model call
   per decision, and its failures are hard to test.
3. **Deterministic checks**: path rules, rule matching, command parsing, address checks, all in
   plain code with tests, and the user asked for anything they don't decide.

## Decision
Option 3. Every allow, ask or deny decision is made by code that gives the same answer for the
same input and is covered by tests, including the attack tests in `tests/security/`. A model's
output can inform the user (for example, explaining a command) but never makes a decision.
When a check can't decide (an unparsable command, an error), the answer is "ask".

## Consequences
- Decisions are predictable, explainable ("denied by rule `run_shell(curl *)` from your user
  settings") and testable offline.
- Fuzzy cases the rules don't cover end up as questions to the user; modes and rules must keep
  those rare enough that the user still reads them.
- New tools must declare what they touch (paths, commands, URLs) so the checks can see it; a
  tool that hides its effects behind an opaque argument gets the strictest treatment.
