# 0020. Watch the keyboard on a thread during agent turns

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
While the agent works, the terminal isn't reading input. Ctrl+C stops a turn, but users expect
Esc to work too (as in other coding agents), and anything typed during a turn either echoes
into the middle of the agent's output or waits invisibly in the console buffer. The agent loop
is synchronous (ADR 0013), so it can't also wait for key presses.

## Options
1. **Ctrl+C only**: no new code; Esc does nothing and type-ahead is messy.
2. **Make the whole app asynchronous** with a full-screen input layer: a large rewrite.
3. **A background thread that reads keys during a turn**: Esc calls `_thread.interrupt_main()`,
   which raises `KeyboardInterrupt` in the main thread, reusing the existing cancel-and-roll-back
   path; other printable keys are collected and pre-filled at the next prompt.

## Decision
Option 3 (`harness/tui/keys.py`), with `msvcrt` on Windows and cbreak mode plus `select` on
POSIX. The watcher pauses while an approval prompt reads the keyboard. Without a console
(pipes, tests) it does nothing.

## Consequences
- Esc and Ctrl+C behave the same. The interrupt is handled when the main thread next runs Python
  code: immediately while text streams, but only after the model's first token if the model is
  still reading a long prompt.
- Keys typed during a turn appear at the next prompt; arrow keys and other special keys are
  dropped.
- Logic is tested with a fake keyboard; the real console path needs a manual check.
