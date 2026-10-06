# 0032. Run commands in an OS sandbox where the system offers one

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Lessons 29-34 stop what text analysis can see: command smuggling, writes to protected paths named in a
command, secrets in the environment, hostile instructions, runaway use. One attack stays open in the lab:
a program that **builds a protected path while it runs** (`open('.g'+'it/hooks/pre-commit', 'w')`).
Reading text can't evaluate a program; nothing short of limiting what the process can do closes it. The same
goes for a script that does something the user didn't read (`python script.py`).

## Options
1. **Do nothing; document the gap.** Honest, leaves T4 and T15 partly open.
2. **A sandbox we write** (restricted tokens on Windows, seccomp on Linux). Large, easy to get subtly wrong,
   and a security product in its own right.
3. **Use the OS's own mechanism where it exists:** bubblewrap on Linux, `sandbox-exec` on macOS; on
   Windows, point to WSL 2, containers and virtual machines.
4. **Require containers** for the whole agent. Strong, heavy, and not the "install and go" experience.

## Decision
Option 3 (`harness/security/sandbox.py`).

- `detect()` finds `bwrap` or `sandbox-exec`; Windows has none.
- **Policy:** the file system is read-only except the workspace and a fresh temporary folder; protected
  folders and files that exist inside the workspace are read-only again; optionally no network; a new process
  namespace, killed with the parent. bubblewrap gets this as ordered mounts (a later mount of a path wins);
  `sandbox-exec` as a profile (the last matching rule wins).
- `run_command` wraps the argv; the tool description tells the model what the sandbox does.
- Settings `sandbox` (`off`, `auto`, `on`; default `auto`) and `sandbox_network` (default true), never from a
  project. `on` without a sandbox **fails closed**: `run_shell` refuses, and the app warns at start.
- The sandbox does **not** change permission decisions in this release. Making sandboxed commands
  cheaper to approve (the way a sandbox lets some agents auto-allow commands) is a later, separate decision.
- Testing: the wrappers are pure string-building and are unit-tested everywhere; one real test runs where
  bubblewrap exists and is skipped elsewhere; the attack lab uses the sandbox automatically when present, and
  keeps the run-time-built-path attack as an expected failure when it is not.

## Consequences
- Where a sandbox exists, an approved or injected command can no longer change `.git/hooks`, other
  protected folders, or anything outside the workspace.
- **Windows users get no sandbox from us** and the docs say so, with the practical alternatives. The lab
  shows one expected failure there, by name.
- **We have not run bubblewrap or `sandbox-exec` in development** (the development machine is Windows). Their
  command lines follow the tools' documented behavior and are tested as strings; a bug in the real behavior is
  possible and the first thing to check on Linux or macOS.
- The protection covers folders that exist at the time; a command can create a missing protected folder.
- `sandbox_network: false` breaks package installs and pushes inside the sandbox; that is why it is off by default.
- Not done: a Docker/Podman runner (a natural third backend), per-command network rules, making sandboxed
  commands easier to approve.
