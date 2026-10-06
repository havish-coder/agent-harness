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
| `context_window` | integer | `8192` | | Context size requested from Ollama (`num_ctx`). Ignored by other providers. |
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
| project settings that set `status_line` (it runs a program), `additional_directories` (it widens access) or `permission_mode` (it decides what runs without asking) | warning; the value is ignored |
| project settings with `allow` rules | warning; the allow rules are ignored, `ask` and `deny` rules are kept |
| a rule that can't be read (`run shell`, `run_shell()`), or an unknown key under `permissions` | error |
| a rule naming a tool that doesn't exist | warning at start |
