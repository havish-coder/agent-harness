# 0060. Plugins are text with options, installed for you, and yours win every clash

- **Status:** Accepted
- **Date:** 2026-10-13

## Context
The user asked for a way to add a plugin and then customize it. The harness already reads four kinds of text from your folder and the
project's: commands ([ADR 0021](0021-markdown-prompt-commands.md)), skills ([ADR 0047](0047-skills-load-on-demand-and-are-text-only.md)), sub-agents ([ADR 0045](0045-sub-agents-share-permissions-not-conversations.md)) and output styles ([ADR 0022](0022-output-styles-and-status-line.md)). Sharing a set of them meant copying
files into four folders by hand. Making one fit your project (your language, your compiler) meant editing someone else's text.

Asked what a plugin may contain, the user chose **text only** (commands, skills, agents, styles: no hooks, no MCP servers, nothing that
runs a program), and **options you set**.

## Options
1. **Document a folder layout** and let people copy files. No install, no options, no way to turn a set off.
2. **Plugins that can run code** (hooks, MCP servers, scripts), like editor extensions. Powerful, and a plugin becomes a program you
   installed without reading. The user chose against it.
3. **A plugin is a folder of the four kinds of text plus a manifest with typed options**, installed into your user folder by a command,
   turned on and off as a unit, its `{{option}}` placeholders filled with your values when it is loaded.

## Decision
Option 3, in a new `harness/plugins.py`:

- **Layout**: `plugin.json` (`name`, `version`, `description`, `options`) and any of `commands/`, `skills/`, `agents/`, `styles/`, each
  exactly like the user's own folders. Installed in `~/.harness/plugins/NAME/`; on/off and the values in `~/.harness/plugins.json`.
- **Install** copies a folder, or runs `git clone --depth 1 -- URL` and drops `.git`. It refuses a plugin with a link in it (a link could
  copy a file from elsewhere on this computer into a skill the agent reads), one over 300 files or 2 MB, and one already installed
  (`--force` replaces it and keeps your values).
- **Options are typed** (`string`, `number`, `boolean`, `choice`), checked when set and when loaded. **A value that looks like a secret
  is refused** (the same patterns that redact secrets in tool results). The values are stored in plain text and become part of what the
  model reads.
- **Loading**: each of the four loaders reads the enabled plugins' folders **after** the built-ins, yours and the project's, with source
  `plugin NAME`, and fills placeholders as it reads. A name already taken is skipped with a warning: a plugin never replaces a built-in or
  anything of yours.
- **Standing**: a plugin's text is instructions with the standing of your own files in `~/.harness`. You installed it, so it isn't
  untrusted content. A project can't install or bring one, so a cloned repository gains nothing from this. Everything the agent then
  does goes through the permissions as always.
- **`/plugin`**: list, install, enable, disable, remove, config. A change reloads the commands, skills, agents and styles, and rebuilds the
  prompt. The web page's Settings show the same, with a switch and a form per plugin, and send the same commands.

## Consequences
- Sharing a workflow is one folder or one repository, and fitting it to a project is `/plugin config`.
- A plugin can still say anything to the agent. Installing one is trusting its author with instructions, as reading a blog post into your
  `HARNESS.md` would be. `/plugin install` says so and shows where the files are.
- Text only rules out plugins that need a program. A hook or an MCP server stays something the user adds to their settings themselves,
  where it is visible.
- Updates are a `--force` install; there is no version check or registry. That is enough for a handful of plugins from people you know.
