# Configuration reference

All settings, their types and defaults. Every setting can also be given as an environment
variable `HARNESS_<NAME>` (upper case) and most as a flag. How the layers combine:
[Configuration](../user-guide/configuration.md).

| Setting | Type | Default | Flag | Description |
|---|---|---|---|---|
| `provider` | string | `"ollama"` | `--provider` | Where the model runs; see [models](../user-guide/models.md). |
| `model` | string or null | provider's default | `--model` | Model name. |
| `base_url` | string or null | provider's default | `--base-url` | Server address. |
| `fallback_model` | string or null | `null` | `--fallback-model` | Second model (same provider) used after retries run out. |
| `temperature` | number or null | `null` (model default) | | Sampling temperature. |
| `context_window` | integer | `8192` | | Context size requested from Ollama (`num_ctx`), and the window the harness plans for. For other providers it overrides the window the harness knows from the model name ([context](../user-guide/context.md)). |
| `microcompact` | boolean | `true` | | When the conversation fills the window, replace the oldest results of re-runnable tools (`read_file`, `grep`, `glob`, `list_dir`, `run_shell`, `web_fetch`) with short notes instead of stopping ([context](../user-guide/context.md#when-the-window-fills-clearing-old-results)). |
| `microcompact_keep` | integer | `2` | | The newest this many results of those tools that are big enough to be worth a note (about 150 tokens) are kept whole (at least 1). |
| `auto_compact` | boolean | `true` | | When clearing old results isn't enough and the conversation no longer fits the window, ask the model to summarise the older messages and carry on from the summary ([context](../user-guide/context.md#summarising-the-conversation-compact)). `/compact` works either way. |
| `save_chats` | boolean | `true` | `--no-save` | Keep each conversation on disk so it can be resumed ([chats](../user-guide/chats.md)). Not accepted from project settings. |
| `chat_retention_days` | integer | `30` | | Delete this project's saved chats not used for this many days when a session starts; `0` keeps them. Not accepted from project settings. |
| `memory` | boolean | `true` | | Read `HARNESS.md` / `AGENTS.md` / `HARNESS.local.md` files into the system prompt ([memory](../user-guide/memory.md)). Not accepted from project settings. |
| `auto_memory` | string | `"ask"` | | Notes the agent saves for itself ([notes](../user-guide/auto-memory.md)): `ask` asks each time, `on` saves without asking while the chat has read no untrusted content, `off` removes the tools. Not accepted from project settings. |
| `journal` | string | `"ask"` | | The project's progress journal ([journal](../user-guide/journal.md)): `ask` offers one the first time a turn changes something, `on` keeps one without asking, `off` neither reads nor writes it. `"never"` in the question writes `off` to `.harness/settings.local.json`. Not accepted from project settings. |
| `subagents` | boolean | `true` | | Give the agent `delegate` and the sentence in the prompt that says when to use it ([sub-agents](../user-guide/sub-agents.md)). A project may set it. |
| `background_tasks` | boolean | `true` | | Let commands run in the background: the `background` parameter of `run_shell`, `task_output` and `task_stop` ([background tasks](../user-guide/background-tasks.md)). A project may set it. |
| `skills` | boolean | `true` | | Read skills: their list in the prompt, `use_skill`, and the commands ([skills](../user-guide/skills.md)). A project may set it. |
| `tool_search` | string | `"auto"` | | Hold back the definitions of rarely used tools until the model finds them with `tool_search`: `auto` (when the definitions take more than 15% of the window; an MCP server's tools when they alone take more than 15%), `on`, `off` ([tool search](../user-guide/tool-search.md)). A project may set it. |
| `todo` | boolean | `true` | | Give the agent the `todo_write` tool, the prompt sentence that says when to use it, and the nudge when it tries to finish with items open ([todo](../user-guide/todo.md)). A project may set it. |
| `file_history` | boolean | `true` | | Keep a copy of each file before `edit_file` or `write_file` changes it, for `/undo` and `/rewind` ([undo](../user-guide/undo.md)). Not accepted from project settings. |
| `max_output_tokens` | integer | `4096` | | Longest reply the model may write, in tokens. Stops a model that keeps repeating itself; a reply cut off here ends with a note. |
| `max_steps` | integer | `20` | `--max-steps` | Maximum model calls per request. |
| `stream` | boolean | `true` | `--no-stream` | Show answers as they are generated. |
| `think` | boolean | `false` | `--think` | Ask thinking models for separate reasoning. |
| `shell` | string or null | `null` (auto) | | `bash`, `pwsh` or `powershell` for `run_shell`. |
| `max_retries` | integer | `4` | | Retries for temporary model-server failures. |
| `output_style` | string | `"default"` | | The [output style](../user-guide/styles-and-status.md) to start with. |
| `status_line` | string or null | `null` | | A command whose first output line replaces the status line. Not accepted from project settings. |
| `permission_mode` | string | `"default"` | `--mode`, `--yes` | `default`, `accept-edits`, `plan` or `bypass` ([permissions](../user-guide/permissions.md)). Not accepted from project settings. |
| `permissions` | object | `{}` | | `{"allow": [...], "ask": [...], "deny": [...]}`, rules like `run_shell(git status*)`. Rules from all layers add up. Project settings may not add `allow` rules. In the environment: JSON. |
| `sandbox` | string | `"auto"` | | `off`, `auto` or `on`: run commands in an OS sandbox ([the command sandbox](../user-guide/sandbox.md)). Not accepted from project settings. |
| `sandbox_network` | boolean | `true` | | May sandboxed commands use the network? Not accepted from project settings. |
| `audit_log` | boolean | `true` | | Keep the [audit log](../user-guide/audit-and-limits.md) in `~/.harness/audit/`. Not accepted from project settings. |
| `redact_secrets` | boolean | `true` | | Hide secrets in tool results and exported chats. Not accepted from project settings. |
| `limits` | object | `{"tool_calls": 500, "cost": 5.0, "tokens": null, "minutes": null}` | `HARNESS_LIMITS` (JSON) | Per-chat limits; `null` = none. Layers change only the keys they name. Not accepted from project settings. |
| `hooks` | object | `{}` | `HARNESS_HOOKS` (JSON) | `{"pre_tool_use": [{"command": "...", "match": "run_shell(git push*)", "timeout": 10}], "post_tool_use": [...], "user_prompt_submit": [...]}`. Hooks from all layers add up; a project's hooks run only in a trusted folder ([hooks](../user-guide/hooks.md)). |
| `web_fetch` | boolean | `true` | | Give the agent the `web_fetch` tool ([Reading web pages](../user-guide/web.md)). |
| `web_allow_local` | list of strings | `[]` | `HARNESS_WEB_ALLOW_LOCAL` (separated like `PATH`) | `host` or `host:port` entries `web_fetch` may reach on your own machine or network, such as `localhost:3000`. Not accepted from project settings. |
| `fence_untrusted` | boolean | `true` | | Wrap file text, command output and web pages in `<untrusted>` tags and tell the model they are data ([untrusted content](../user-guide/untrusted-content.md)). Not accepted from project settings. |
| `shell_env_keep` | list of strings | `[]` | `HARNESS_SHELL_ENV_KEEP` (separated like `PATH`) | Environment variables commands may see even though they look secret (for example `SSH_AUTH_SOCK` to let `git push` use your ssh agent). Names are compared without case. Not accepted from project settings. |
| `mcp_servers` | object | `{}` | `HARNESS_MCP_SERVERS` (JSON) | Programs that give the agent tools over MCP: `{"name": {"command": "npx", "args": [...], "env": ["VAR_NAME"], "trusted": false}}`. `env` lists names of variables to pass on even though they look secret; `trusted` means the results are yours, not untrusted content. Servers from all your layers add up; one of the same name replaces the earlier. **Only from your user settings**, the environment or a flag: not from project settings, nor from `settings.local.json` ([MCP servers](../user-guide/mcp.md)). |
| `additional_directories` | list of strings | `[]` | | Folders outside the workspace the file tools may also use ([workspace](../user-guide/workspace.md)). Relative to the workspace. Not accepted from project settings. |
| `prices` | object | `{}` | | Extra prices: model-name prefix → `{"input", "output", "cache_read", "cache_write"}` in US dollars per million tokens. Merged across layers. |

Environment values are converted to the setting's type: booleans accept `1`, `true`, `yes`,
`on` (anything else is false); numbers must parse; lists are separated like `PATH` (`;` on Windows,
`:` elsewhere).

## Files
| Layer | Path |
|---|---|
| user | `~/.harness/settings.json` (or `$HARNESS_HOME/settings.json`) |
| project | `<workspace>/.harness/settings.json` |
| local | `<workspace>/.harness/settings.local.json` |
| secrets | `~/.harness/.env`, `<workspace>/.env` |

## Validation
| Problem | Result |
|---|---|
| unknown setting | warning, with the closest known name |
| wrong type (e.g. `"max_steps": "ten"`, `"stream": 1`) | error |
| invalid JSON | error with the line number |
| a setting named like a secret (`api_key`, `token`, `secret`, `password`) | error |
| a value that looks like an API key (`sk-...`, `sk-ant-...`, `gsk_...`, `AIza...`) | error |
| project settings that set `provider` or `base_url` | warning showing the values |
| a workspace `.env` not ignored by git | warning |
| project settings that set `status_line` (it runs a program), `additional_directories` (it widens access) `permission_mode` (it decides what runs without asking), `shell_env_keep` (it hands your secrets to commands) or `fence_untrusted` (it removes a protection) or `web_allow_local` (it lets web_fetch reach your own network) | warning; the value is ignored |
| project or `settings.local.json` settings that set `mcp_servers` (it starts programs, and a repository could ship either file) | warning; the value is ignored |
| an `mcp_servers` entry without a `command`, with an unknown key, a name that isn't 1-30 letters, digits, `-` or `_` (or contains `__`), `args` or `env` that aren't lists of strings, or `trusted` that isn't a boolean | error |
| project settings with `allow` rules | warning; the allow rules are ignored, `ask` and `deny` rules are kept |
| a rule that can't be read (`run shell`, `run_shell()`), or an unknown key under `permissions` | error |
| a rule naming a tool that doesn't exist | warning at start |
