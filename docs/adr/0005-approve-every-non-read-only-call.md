# 0005. Ask before every tool call that isn't read-only

- **Status:** Accepted, amended by [0026](0026-permission-modes-and-rules.md)
- **Date:** 2026-10-06

## Context
v0.2 adds tools that write files and run shell commands. The full permission system (modes,
allow/deny rules, a path jail) is planned for v0.5. Until then the agent would be able to
change the user's disk with no check at all, and small models do make mistakes: during
development one listed the root of the drive when asked about a workspace folder.

## Options
1. **Wait for v0.5**: simplest now; three releases with no protection.
2. **Ask before tools in a hard-coded "dangerous" list**: fails open for any tool not on the
   list.
3. **Ask before every call whose tool isn't read-only for those arguments**, using the
   fail-closed `read_only` flag from ADR 0004's decorator.

## Decision
Option 3. `Agent` takes an `approve(call, tool) -> bool` callback and calls it for every
validated call where `tool.is_read_only(args)` is false. With no approver, such calls are
refused. The terminal app asks `y` / `n` / `a`lways; `--yes` approves everything.

## Consequences
- New tools are protected automatically unless their author declares them read-only.
- More prompts than strictly necessary (e.g. every edit). v0.5's permission rules will reduce
  them without weakening the default.
- A denial returns a message telling the model not to retry and to ask the user. In live
  tests with `qwen3:4b-instruct` it never retried a denied call (3 of 3 runs).
