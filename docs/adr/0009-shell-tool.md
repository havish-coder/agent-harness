# 0009. A single shell tool, PowerShell on Windows

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
A coding agent must run tests, scripts and tools. The development machine is Windows, where
the available shells are Windows PowerShell 5.1, `cmd.exe` and (sometimes) Git Bash. Models
know bash best, but bash is not always installed on Windows, and `cmd.exe` is the weakest of
the three. Several problems showed up in testing: PowerShell reports exit code 1 for any
failing native command (a program exiting with 3 looked like 1), output in the console code
page garbles non-ASCII text, and commands that wait for input hang forever.

## Options
1. **bash everywhere** (require Git Bash on Windows): one syntax; an install requirement.
2. **cmd.exe on Windows**: always present; poor quoting and error handling.
3. **The platform's native shell**: PowerShell (7 if present, else 5.1) on Windows, bash
   elsewhere, with the shell's name and syntax hints in the tool description.

## Decision
Option 3. Commands run with closed stdin, in a new process group (so a timeout stops the
whole tree), with UTF-8 forced in and out, and with the agent's Python first on `PATH`.
PowerShell commands are wrapped so the real exit code is passed through. The tool is not
read-only for any command until command analysis exists (v0.5).

## Consequences
- Works on a stock Windows install; the model is told it's PowerShell 5.1 and to use `;`.
- Model output written for bash (`ls -la`, `&&`) can fail on 5.1; the failure is visible to the
  model as a normal error, and it can retry.
- Every command needs approval until v0.5's analysis can recognise safe ones.
