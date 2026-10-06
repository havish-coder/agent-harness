# Permissions: modes and rules

Before each tool call the agent wants to make, the harness decides one of three things:

- **allow:** the call runs straight away;
- **ask:** you see what the call would do (with a diff for file changes) and answer;
- **deny:** the call doesn't run, and the model is told why.

Out of the box, anything that only reads (listing, reading, searching) is allowed and everything
else asks. **Modes** and **rules** change that, so routine work stops interrupting you while the
risky things keep asking.

## Answering a question
```text
  ? run_shell wants to run
    python -m pytest -q
    allow? [y]es / [n]o / [a]lways allow this exact command (this session):
```

- `y` runs it once, `n` (or Enter) refuses it. The model is told you said no and asked to check
  with you instead of retrying.
- `a` runs it and remembers the answer **until you quit**. For a command it remembers *this exact
  command*, character for character: `rm *.pyc` stays `rm *.pyc` and never becomes a pattern. For
  a file tool it remembers the tool (`every edit_file call`). `/permissions` shows what you added.
- When the question says **`asking because ...`** the call touches something protected (see below)
  and `a` isn't offered: these always ask.

## Modes
| Mode | Reading | File edits in the workspace | Commands | Use it for |
|---|---|---|---|---|
| `default` | runs | ask | ask | normal work |
| `accept-edits` | runs | **run** | ask | a task you'll review with `git diff` afterwards |
| `plan` | runs | **refused** | **refused** | exploring and planning: the agent describes changes instead of making them |
| `bypass` | runs | **run** | **run** | throwaway folders and containers only |

Choose one at start with `--mode accept-edits` (or `"permission_mode"` in your
[settings](configuration.md)), or switch any time with `/mode plan`; the conversation is kept.
`--yes` is short for `--mode bypass`. The status line shows the mode whenever it isn't `default`.

Even `bypass` keeps two safety nets: **deny rules** and **protected paths** still apply.

## Rules
Rules say what to allow, ask about or deny, per tool and optionally per *subject*: the command for
`run_shell`, the path for file tools.

```json
{
  "permissions": {
    "allow": ["run_shell(python -m pytest*)", "run_shell(git status*)", "run_shell(git diff*)"],
    "ask":   ["edit_file(pyproject.toml)"],
    "deny":  ["run_shell(*curl *)", "run_shell(git push*)", "read_file(secrets/**)"]
  }
}
```

| Rule | Matches |
|---|---|
| `run_shell` | every command |
| `run_shell(git status*)` | commands starting with `git status`; `*` matches anything, spaces too |
| `write_file(src)` | `src` and everything inside it |
| `edit_file(src/*.py)` | Python files directly in `src` (`*` stays inside one folder) |
| `edit_file(src/**)` | everything under `src`, at any depth |
| `*` | every tool |

Paths are relative to the workspace and are compared **after** they're resolved, so
`docs/../src/app.py` is matched as `src/app.py`. On Windows path rules ignore case, like the file
system does.

**Which rule wins.** The strictest answer can't be overruled by a looser one:

1. a **deny** rule refuses the call, in every mode;
2. a **protected path**, or an **ask** rule, asks, in every mode (bypass included);
3. the **mode**: `plan` refuses changes, `bypass` runs everything else, `accept-edits` runs file edits;
4. an **allow** rule runs the call;
5. reading runs;
6. anything else asks.

Deny rules apply to reading too: `read_file(secrets/**)` keeps a folder out of the model's sight.

### How commands are read
A command line is a small program, so rules don't match its text as one string. The harness first
splits it into the **commands it would run**: `a && b | c; d`, the inside of `$(...)`, backticks and
`bash -c '...'`, with wrappers such as `env`, `sudo` and `timeout 60` taken off so the rule sees
the real program (`/usr/bin/git`, `GIT.EXE` and `git` are all `git`).

| Rule | What it needs |
|---|---|
| **deny** and **ask** | matches *any one* command in the line (or the whole text): `deny run_shell(git push*)` stops `echo hi && git push`, `sudo git push`, `bash -c 'git push'` and `echo $(git push)` |
| **allow** | matches *every* command in the line: `allow run_shell(python -m pytest*)` runs `cd project && python -m pytest -q`, but not `python -m pytest; rm -rf src` or `python -m pytest | sh` |

More rules for **allow**, because it grants something:
- A command run with a changed environment or a wrapper (`PYTHONPATH=x python ...`,
  `env LD_PRELOAD=x ...`, `sudo ...`, `timeout 5 ...`) is *not* the command you allowed.
- The program must be spelled as in the rule: `/tmp/evil/python -m pytest` is not `python -m pytest`.
- Redirections count: `python -m pytest > results.txt` is fine (inside the workspace), but
  `> ../x`, `> ~/.bashrc` or `> /etc/...` are not covered.
- A command the reader **can't fully follow** (a here-document, `eval $x`, a program name held in a
  variable, an unbalanced quote, most PowerShell syntax) is never covered by a pattern: it asks, and
  the question says so. `allow run_shell` (the whole tool) and an "always" answer still apply.

A few commands **need no rule at all** when nothing in them reaches outside the workspace:
`cd` into a folder inside it, `pwd`, `echo`, `printf`, `true`, `false` and `sleep`. They count as
reading, so `cd project && pwd` runs even in `default` and `plan` mode. `echo x > file`, `cd ..`
and `cd ~` don't qualify.

The question for a command also lists what the reader noticed, in plain words:

```text
  ? run_shell wants to run
    rm -rf build && git push --force
    ! deletes files (rm -r)
    ! rewrites history on a remote (git push --force)
    allow? [y]es / [n]o / [a]lways allow this exact command (this session):
```

It's a reader of text, not a sandbox: `python script.py` runs whatever the script contains, and
a path assembled at run time (`'.g' + 'it'`) can't be seen. See [Security](../security.md).

### Where rules come from
Rules can be set in every [settings layer](configuration.md). They **add up** instead of
replacing each other, and each keeps its source, shown by `/permissions` and `--show-config`:

```text
mode: default
deny:
  run_shell(*curl *)  (user)
allow:
  run_shell(python -m pytest*)  (local)
  run_shell(echo hi)  (exact)  (session)
```

**Project settings** (`<workspace>/.harness/settings.json`, which arrives with a repository you
clone) may add `ask` and `deny` rules, but **not** `allow` rules or a `permission_mode`: a
repository must not be able to turn off your approvals for itself. Those are ignored with a
warning. Put them in your user settings (`~/.harness/settings.json`) or in the project's
`settings.local.json` (yours, not committed).

In the environment: `HARNESS_PERMISSION_MODE=plan`, and
`HARNESS_PERMISSIONS='{"deny": ["run_shell(git push*)"]}'` (JSON).

A rule naming a tool that doesn't exist (`run_shel`) gets a warning at start.

### Changing rules while you work
| Command | Does |
|---|---|
| `/permissions` | the mode and every rule, with its source |
| `/permissions allow run_shell(npm test*)` | add a rule for this session (also `ask`, `deny`) |
| `/permissions remove run_shell(npm test*)` | remove a rule added this session |
| `/mode [name]` | show the modes, or switch |

Rules from settings files are changed in those files.

## Protected paths
Writing to these always asks, whatever the mode or rules, because something runs what's in them
later, often without you noticing:

| Path | Why |
|---|---|
| `.git/` | git runs hooks and settings from it (`.git/hooks/pre-commit`, `.git/config`) |
| `.harness/` | the agent's own settings, commands and styles |
| `.vscode/`, `.idea/` | the editor runs tasks and settings from them |
| `.husky/`, `.pre-commit-config.yaml` | run on every commit |
| `.github/workflows/` | CI runs it, often with secrets |
| `.envrc` | direnv runs it when you enter the folder |
| `.gitattributes` | can make git run filter programs |

They're matched at any depth (`sub/.git/config` too) and without case. Reading them is fine.

**Commands too.** A shell command asks (in every mode) when it writes to a protected place with
`>`, `>>` or `&>`, or when any word in it names one, so `cp x .git/hooks/pre-commit`,
`sed -i ... .vscode/tasks.json` and `python -c "open('.git/hooks/x', 'w')"` all ask. So do
`git config key value` and `git -c key=value ...`, which can make git run a program (`core.hooksPath`,
`core.fsmonitor`, aliases). Reading with `cat`, `ls`, `grep` and the like, and `git config --get`,
don't. This closes the obvious ways, not all of them: a command that builds the path while it runs
can't be seen by reading its text. An OS sandbox (a later lesson) would close that; until then, don't
use `bypass` in a repository you care about. See [Security](../security.md).

## Secrets and commands
Commands run with a copy of your environment **without secrets**. A variable is removed when its
name contains a word like `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `AUTH`, `COOKIE` or `CREDENTIALS`
(`ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `AWS_SECRET_ACCESS_KEY`, `sessionCookie`), or when its value
looks like an API key (`sk-...`, `gsk_...`). `PATH`, `HOME`, `KEYBOARD_LAYOUT` and the like stay.
So `env`, `echo $ANTHROPIC_API_KEY` and `python -c "import os; print(os.environ)"` can't hand your
keys to the model (and through it, to a cloud provider's logs).

Some tools need a secret-looking variable: `git push` over ssh needs `SSH_AUTH_SOCK`, a deploy script
may need a token. Allow specific names in your user or local settings (a project can't):

```json
{ "shell_env_keep": ["SSH_AUTH_SOCK", "NPM_TOKEN"] }
```

A secret written in a *file* is a different matter: `read_file(".env")` still shows it to the model
(redaction is a later lesson). Keep keys in environment variables, as the
[configuration guide](configuration.md) suggests.

## Refused calls
When a call is denied the model gets a short explanation (`not allowed: plan mode is on ...`)
and is told not to try another way. In our tests with `qwen3:4b-instruct`, plan mode made it
describe the fix instead of making it, and it asked what to do after a refused write to a git hook.
