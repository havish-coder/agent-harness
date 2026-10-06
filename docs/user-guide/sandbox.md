# The command sandbox

Everything else in [permissions](permissions.md) works by **reading**: the command's text, the paths, the
words. That is the right tool for most things and the wrong one for some. A program can build a file name
while it runs (`'.g' + 'it'`), and a script can do anything you can. A **sandbox** doesn't read anything. It
limits what the process is *able* to do.

When a sandbox is on, a command run by the agent can:

- **write only inside the workspace** (and a temporary folder), nowhere else on your disk;
- **not write to the protected folders** inside the workspace (`.git`, `.harness`, `.github/workflows`,
  `.husky`, `.envrc`, ...), even though the rest of the workspace is writable;
- optionally **not use the network** (`sandbox_network: false`);
- read the rest of the system as usual (a sandbox that hid `/usr` would break every tool).

The banner says when it's active: *commands run in a bubblewrap sandbox: they can write only inside the
workspace (and a temporary folder), protected folders are read-only, network allowed*. The model is told too,
so a failed write (`Read-only file system`) isn't a mystery to it.

## Where it works
| System | Sandbox | Notes |
|---|---|---|
| Linux | [bubblewrap](https://github.com/containers/bubblewrap) (`bwrap`) | `apt install bubblewrap`, `dnf install bubblewrap`, ... |
| macOS | `sandbox-exec` | part of the system |
| **Windows** | **none** | there's nothing equivalent that a script can start; see below |

> The wrappers are built and unit-tested on every system, but only *run* where the tool exists. This
> project's development machine is Windows, so the Linux and macOS sandboxes are tested as command lines
> and by one real test that is skipped here; try it on your own machine with
> `pytest tests/test_sandbox.py tests/security -q` and tell us what you see.

## Settings
```json
{ "sandbox": "auto", "sandbox_network": true }
```

| `sandbox` | Does |
|---|---|
| `off` | commands run directly |
| `auto` (default) | use a sandbox when the machine has one, otherwise run directly and say nothing |
| `on` | always use one; if there isn't one, **`run_shell` refuses to run** and the app says why |

`sandbox_network: false` also cuts the network for commands (so `pip install` and `git push` fail inside the
sandbox). Both settings are user or local only: a project can't turn the sandbox off.

## What it doesn't do
- **It protects the folders that exist.** `.git` can be made read-only only if it is there; a command can
  still create `.vscode/` if it doesn't exist yet. (The permission layer asks about commands that mention it.)
- **The workspace is writable.** An injected command can still change your source files. That's the job of
  approvals, taint and review (`git diff`), not the sandbox.
- **It doesn't hide your files from commands.** The system is readable, including your home folder. A command
  can still *read* a secret there and print it; redaction and secret-free environments handle what they
  can, and the sandbox with `sandbox_network: false` stops it being sent anywhere.
- **It covers `run_shell` only.** The file tools are confined by the [path jail](workspace.md), `web_fetch` by its
  [address guard](web.md), hooks by trust.

## On Windows
Use the agent where the project can't hurt anything: inside **WSL 2** (then the Linux sandbox is available,
with bubblewrap installed there), in a **container** or a **dev container** with only the project mounted, or
in a **virtual machine**. These are your tools to set up; Agent Harness doesn't start them for you. Combine
them with `--mode default` and the usual rules: a sandbox changes what a mistake can cost, not whether it is
made.
