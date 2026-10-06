# Hooks

A **hook** is a command of yours that the agent runs at a fixed point in its work. Hooks let you add
rules that a permission pattern can't express ("no pushes on Fridays", "ask before touching anything in
`migrations/`"), react to what happened (run the formatter after every edit) and check what you type
before the model sees it.

```json
{
  "hooks": {
    "pre_tool_use": [
      { "match": "run_shell(git push*)", "command": "python .harness/hooks/no_friday_pushes.py" }
    ],
    "post_tool_use": [
      { "match": "edit_file", "command": "ruff format --quiet", "timeout": 20 }
    ],
    "user_prompt_submit": [
      { "command": "python .harness/hooks/no_secrets_in_prompts.py" }
    ]
  }
}
```

## Events
| Event | Runs | A hook can |
|---|---|---|
| `user_prompt_submit` | when you press Enter, before the model sees the message | block it; add context |
| `pre_tool_use` | before a tool call runs | deny it; make it ask; (for a routine question) allow it; add context |
| `post_tool_use` | after a tool call ran | add context for the model (a linter's output) |

`match` limits `pre_tool_use` and `post_tool_use` to some calls and uses the same syntax as
[permission rules](permissions.md#rules): `edit_file`, `write_file(config/**)`, `run_shell(git push*)`. For
commands it matches like a deny rule: any command inside the line counts (`echo hi && git push`
matches `run_shell(git push*)`). Without `match`, a hook sees every call. `timeout` is in seconds
(default 10, at most 60).

## What a hook receives and answers
The hook gets a JSON object on standard input:

```json
{ "event": "pre_tool_use", "tool": "run_shell", "arguments": {"command": "git push origin main"},
  "subject": "git push origin main", "mode": "default", "tainted": false, "cwd": "/path/to/project" }
```

(`post_tool_use` adds `"result"`, `user_prompt_submit` has `"prompt"` instead of the tool.) Its answer is its
exit code and output:

| Answer | Meaning |
|---|---|
| exit 0, no output | no opinion |
| exit 0 and a JSON object | `{"decision": "allow" \| "ask" \| "deny", "reason": "...", "context": "..."}`; every field is optional |
| exit 2 | deny; what the hook wrote to standard error is the reason |
| any other exit code, a timeout, output that isn't a JSON object | the hook **failed** |

A small hook in Python:

```python
import json, sys
call = json.load(sys.stdin)
if "git push" in call["subject"]:
    json.dump({"decision": "deny", "reason": "pushes are done by a person, not the agent"}, sys.stdout)
```

`context` is text for the model or for you: it is appended to the tool result (`post_tool_use`), shown as a note in
the approval question (`pre_tool_use`) or added to your message (`user_prompt_submit`). For `user_prompt_submit` only
`deny` and `context` mean anything: there is nobody to ask. It is your script's text,
so it isn't fenced as [untrusted](untrusted-content.md).

## How hooks and permissions fit together
Permissions decide first, then the hooks speak. The rules are short:

- A hook can only make things **stricter**: `deny` refuses the call, `ask` makes it ask, whatever the
  mode or rules said.
- A hook's `allow` only turns the **routine** question (*it can change things*) into a yes. It can't
  override a deny rule, a protected path, an ask rule, plan mode, or the pause after
  [untrusted content](untrusted-content.md).
- With several hooks, the strictest answer wins.
- A hook that **fails** never allows: if the call would have run, it **asks** and says why (*the hook
  "..." failed: exit code 1*). A broken hook is annoying, not a hole.
- A refused call tells the model the hook's reason and to do what it says. If your script names an
  alternative ("write to docs/notes.txt instead"), the model usually follows it.

## Where hooks may come from
| Source | Runs |
|---|---|
| your user settings (`~/.harness/settings.json`), `settings.local.json`, the environment | always |
| a project's `.harness/settings.json` | **only in a folder you have trusted** (`/trust`) |

A hook is a program, and a repository you just cloned shouldn't get to run programs on your machine
(it could ship a `pre_tool_use` hook that reads your files). In a folder that isn't trusted the app starts
with a notice listing the project hooks it did **not** run. `/hooks` shows every hook in force and where it
came from.

## Environment
Hooks run in the workspace folder, with your environment **minus secrets** (the same rule as shell commands: a
variable whose name has KEY, TOKEN, SECRET, PASSWORD... is removed unless it is in `shell_env_keep`), plus
`HARNESS_HOOK_EVENT` and `HARNESS_WORKSPACE`.

## Cost
Each matching hook starts a process every time: tens of milliseconds for a shell script, a few hundred for
Python. Use `match` so a hook only runs for the calls it cares about, and keep `post_tool_use` hooks quick.
