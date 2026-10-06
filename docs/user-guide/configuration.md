# Configuration

Every option can be set in a file, so you don't have to type flags each time. Settings are
read from several places; later ones override earlier ones:

| # | Layer | File | Use it for |
|---|---|---|---|
| 1 | defaults | (built in) | |
| 2 | **user** | `~/.harness/settings.json` | your preferences on this machine, for every project |
| 3 | **project** | `<workspace>/.harness/settings.json` | settings everyone on the project shares; commit it |
| 4 | **local** | `<workspace>/.harness/settings.local.json` | your personal overrides for one project; don't commit it |
| 5 | environment | `HARNESS_<NAME>` variables | scripts, CI, one-off changes |
| 6 | flags | `--model`, `--max-steps`, ... | this run only |

(`~` is your home folder, e.g. `C:\Users\you`. Set `HARNESS_HOME` to use another folder
instead of `~/.harness`.)

## Example
`~/.harness/settings.json`:
```json
{
  "provider": "ollama",
  "model": "qwen3:4b-instruct",
  "max_steps": 25
}
```

`my-project/.harness/settings.local.json` (just for you, in one project):
```json
{
  "provider": "groq",
  "model": "llama-3.3-70b-versatile",
  "fallback_model": "llama-3.1-8b-instant"
}
```

See every setting in the [configuration reference](../reference/configuration.md).

## See what's in effect
```bash
harness --show-config
```
```text
provider        'groq'                       (local)
model           'llama-3.3-70b-versatile'    (local)
max_steps       25                           (user)
stream          True                         (default)
...
```
Each line says which layer the value came from.

## Mistakes are caught early
- An unknown setting is a **warning** with a suggestion:
  `warning: project: unknown setting 'temprature' (did you mean 'temperature'?)`
- A wrong type or invalid JSON is an **error** naming the file and the line.

## Prices
The agent knows the prices of Anthropic's Claude models (as of 2026-10-06) and treats models on
your computer as free. For any other model, add its price, in US dollars per million tokens
(the numbers below are only an example):

```json
{
  "prices": {
    "llama-3.3-70b": {"input": 0.59, "output": 0.79},
    "my-model": {"input": 1.0, "output": 4.0, "cache_read": 0.1, "cache_write": 1.25}
  }
}
```

Names match by prefix, so `llama-3.3-70b` also covers `llama-3.3-70b-versatile`. Price tables
from different layers add up. Check your provider's pricing page for current numbers.

## API keys: never in settings files
Settings files are meant to be shared and committed, so they must not hold secrets. A setting
named like `api_key`, `token` or `password`, or a value that looks like an API key, is refused.

Keys go in environment variables (see [models](models.md)), or in a `.env` file:

```text
# ~/.harness/.env  (for all projects)    or    <workspace>/.env  (for one project)
GROQ_API_KEY=gsk_...
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` files are loaded at startup: first `~/.harness/.env`, then the workspace's. A variable
that is already set in your environment is never overridden. If the workspace's `.env` isn't
ignored by git, you get a warning, because one `git add .` would publish your keys. Add `.env`
to the project's `.gitignore`.

## A warning about shared project settings
`provider` and `base_url` decide **where your prompts and your code are sent**. If a project's
`.harness/settings.json` sets them (for example in a repository you just cloned), you'll see:

```text
warning: project settings choose where your prompts are sent: base_url='http://203.0.113.9/v1'
```

Check that address before you continue.

## What to commit
In your own projects, commit `.harness/settings.json` and ignore the rest:

```text
# .gitignore
.env
.harness/settings.local.json
```
