# 0030. Hooks are user scripts that can tighten decisions, and never loosen the protected ones

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Permission rules (ADR 0026) match patterns. Users want things a pattern can't say: "no pushes on Fridays",
"ask before touching a migration unless a ticket id is in the branch name", "run the formatter after every
edit", "don't let me paste a password into a prompt". The usual answer is a **hook**: the user's own command,
run by the harness at an event, deciding or reacting.

A hook is also a way to run code. That raises three questions this decision has to answer: how does a hook
combine with the permission decision, what happens when a hook breaks, and who gets to install one.

## Options
1. **Hooks decide.** The hook's answer replaces the permission decision. Flexible; a hook that says `allow` could
   override a deny rule or a protected path, and a trivial `echo allow` hook would switch the safety layer off.
2. **Hooks only observe** (logging, formatting). Safe, but can't enforce anything.
3. **Hooks can tighten, and loosen only the routine case.** A hook may deny or force a question, and
   its `allow` only settles a plain "it can change things" question.
4. **Hooks as a plugin API in Python** (imports, in-process). Faster and richer, but runs the user's code
   inside the agent's process and memory, with the agent's secrets.

For failure: treat a broken hook as "no opinion" (permissive), as a refusal (strict), or as a question.
For origin: any settings layer, none, or only trusted ones.

## Decision
Option 3, as commands run in a separate process (`harness/hooks.py`):

- **Events:** `user_prompt_submit`, `pre_tool_use`, `post_tool_use`. A `match` in rule syntax narrows tool
  events; for commands it matches like a deny rule (any command in the line).
- **Protocol:** JSON on standard input; the answer is the exit code and standard output: exit 2 denies
  with standard error as the reason; exit 0 with `{"decision", "reason", "context"}` answers; empty output is
  no opinion. Anything else is a failure.
- **Combination:** `deny` and `ask` apply whatever else was decided. `allow` only replaces a *routine* ask
  (reason `it can change things`): never a deny rule, protected path, ask rule, plan mode, or the pause after
  untrusted content (ADR 0028). With several hooks the strictest answer wins.
- **Failure:** a hook that times out, crashes, or answers badly never allows. Where the call would have run,
  it asks, and the question says which hook failed and why.
- **Origin:** hooks from user settings, local settings and the environment always run; hooks from a project's
  settings run only in a trusted folder (ADR 0028). The app lists the project hooks it did not run.
- **Environment:** hooks run in the workspace with the secret-free environment of shell commands (ADR 0027).
  Output read from a hook is capped, and each hook has a time limit (default 10 s, at most 60).

## Consequences
- Users can enforce policies no pattern can state, and a hook can never be the way a protection is switched
  off; it is a way to add protections.
- A broken or slow hook costs the user a question or some seconds, never a hole. That is the point of
  failing toward asking.
- Hooks run a process per call, so the cost shows (tens to hundreds of ms); `match` is how to keep it low.
- A hook is still arbitrary code with the user's rights: installing one is installing a program. The trust
  rule keeps a repository from doing it for you; it can't make a user's own hook correct.
- While the chat is tainted a hook's `allow` is not honored at all (a hook can't tell, from the call alone,
  whether it was steered by what the agent read). The payload carries `"tainted"`, so a hook can also choose
  to be stricter in that state.
- Not done: hooks for session start/stop, hooks that rewrite a call's arguments, HTTP hooks (these would need the
  network guard of ADR 0029).
