# Writing a plugin

A plugin is a folder with a `plugin.json` and at least one of four folders. Everything in it is text. For what users do with it, see
[plugins](../user-guide/plugins.md).

```text
my-plugin/
  plugin.json
  commands/NAME.md            slash commands: /NAME
  skills/NAME/SKILL.md        skills (and any files next to SKILL.md)
  agents/NAME.md              sub-agents for delegate
  styles/NAME.md              output styles for /style
  README.md                   anything else is copied and ignored
```

## `plugin.json`
```json
{
  "name": "code-review",
  "version": "1.0.0",
  "description": "A /review command for the language and strictness you choose.",
  "options": {
    "language":     {"type": "choice", "choices": ["any", "python", "cpp"], "default": "any", "description": "your project's language"},
    "strictness":   {"type": "choice", "choices": ["gentle", "normal", "strict"], "default": "normal"},
    "max_findings": {"type": "number", "default": 5, "description": "at most this many findings"},
    "tests_too":    {"type": "boolean", "default": false},
    "team":         {"type": "string", "default": "", "description": "your team's name, for the review's heading"}
  }
}
```

| field | required | rules |
|---|---|---|
| `name` | yes | a-z, 0-9 and `-`, starting with a letter, at most 40 characters; the folder it is installed in |
| `version` | no | any text (`0.0.0` if missing); shown by `/plugin` |
| `description` | no | one line, at most 200 characters |
| `options` | no | each key: a-z, 0-9, `-` and `_`, starting with a letter |

An option has a `type` (`string`, `number`, `boolean`, `choice`), an optional `default` (it must fit the type; without one: the first
choice, `false`, `0` or `""`), `choices` for a `choice`, and a `description` for `/plugin config` and the web page's form.

## Placeholders
`{{key}}` anywhere in a command, `SKILL.md`, agent or style is replaced by the user's value for option `key` (or its default) when the
plugin is loaded. Booleans become `true` or `false`. A `{{word}}` that isn't one of the plugin's options is left as it is. Files next to a
`SKILL.md` are read as they are, without placeholders.

```markdown
---
description: review your uncommitted changes, or a file you name
argument-hint: [file, or what to focus on]
---
Review code in this project. Language: {{language}}. Strictness: {{strictness}}.
What to review: $ARGUMENTS
...
```

`$ARGUMENTS`, `$1`, `$2` ... are the command's own ([commands](../user-guide/commands.md#your-own-commands)): they are filled when the
command runs, from what the user typed after it.

## The files
They are the same files a user writes in `~/.harness`:

- **Commands**: [commands](../user-guide/commands.md#your-own-commands) (frontmatter `description`, `argument-hint`).
- **Skills**: [skills](../user-guide/skills.md) (frontmatter `description`, `user-only`).
- **Agents**: [sub-agents](../user-guide/sub-agents.md) (frontmatter `description`, `tools`, `max_steps`, `model`).
- **Styles**: [output styles](../user-guide/styles-and-status.md) (frontmatter `description`).

A name that is already taken (a built-in, the user's own, the project's, or another plugin's loaded first) is skipped with a warning, so
choose names that say whose they are (`acme-review` rather than `review`) if you share a plugin widely.

## Limits
- **Text only.** There is no way for a plugin to run a program, add a hook, an MCP server, a permission rule or a setting. If your idea
  needs one, document the setting for the user to add.
- **Plain files**: no links. At most 300 files and 2 MB in all.
- A user's values must not be secrets: values that look like keys or tokens are refused. If your plugin needs a key, tell the user which
  environment variable to set, and refer to it by name in your text.

## Trying it
```bash
harness
```
then `/plugin install path/to/my-plugin`, `/plugin` to check what it adds, and `/plugin install --force path/to/my-plugin` after each
change (the user's values are kept).

## Sharing it
Put the folder at the root of a git repository. Users install it with `/plugin install https://github.com/you/my-plugin.git`. The harness
clones it with `--depth 1` and drops the `.git` folder: updates are a `--force` install.
