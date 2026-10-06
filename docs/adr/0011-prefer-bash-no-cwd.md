# 0011. Prefer bash on Windows too, and drop the `cwd` argument

- **Status:** Accepted
- **Date:** 2026-10-06
- **Supersedes:** [0009](0009-shell-tool.md)

## Context
ADR 0009 chose PowerShell on Windows and gave `run_shell` a `cwd` argument. Measuring the
agent on a fix-and-test task showed both were mistakes:

- The model wrote `cd project && python -m pytest tests/` again and again, although the tool
  description said `&&` doesn't work in Windows PowerShell 5.1. With PowerShell, only 1 of 3
  runs managed to run the tests; with Git for Windows' bash, 4 of 5.
- With `cwd`, the model combined `cwd="project"` with paths that already started with
  `project/`, so they pointed to `project/project/...`. At temperature 0 it did this in every
  recording, repeating the failing command up to 6 times.

## Options
1. Keep PowerShell and `cwd`; rewrite `&&` and fix doubled paths automatically: brittle.
2. **Use bash when available, and run every command in the workspace root**, letting the
   model write `cd folder && ...` as it naturally does.

## Decision
Option 2. On Windows, `run_shell` uses Git for Windows' `bash.exe` when it is installed (never
`System32ash.exe`, which starts WSL), then PowerShell 7, then Windows PowerShell 5.1. The
`HARNESS_SHELL` environment variable (`bash`, `pwsh`, `powershell`) overrides the choice.
`run_shell(command, timeout)` always starts in the workspace root.

## Consequences
- Windows users with Git installed get the shell models write best.
- One fewer argument means one fewer way to be wrong; `cd` inside a command works in all
  three shells (`&&` in bash and PowerShell 7, `;` in 5.1).
- The tool's result still says where the command ran (`in .`).
