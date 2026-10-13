# Plugins

A plugin is a folder of text that adds [slash commands](commands.md), [skills](skills.md), [sub-agents](sub-agents.md) and
[output styles](styles-and-status.md) in one step, with **options you set**: the language your project is in, the compiler you use, how
strict a review should be. You install it once, for every project.

```text
> /plugin install examples/plugins/cpp-helper
installed cpp-helper 1.0.0 (on): C++ know-how for the agent (a skill it loads when a task is about C++) and a /cpp-test command ...
  adds: commands /cpp-test · skills cpp
  compiler = g++ (g++, clang++, cl)
  standard = c++17 (c++17, c++20, c++23)
  warnings = true (boolean)
A plugin's text becomes instructions the agent follows, like your own files in ~/.harness. Read it before you use it: C:\Users\<you>\.harness\plugins\cpp-helper
> /plugin config cpp-helper compiler clang++
cpp-helper: compiler = clang++
> /cpp-test trie.cpp
```

## What a plugin can and can't do
It can add text: commands, skills, agents and styles, each as Markdown files like the ones you write yourself. It **can't run anything**:
no hooks, no MCP servers, no programs, no permission rules or settings. What it adds is instructions, so the agent follows them as it
follows your own files, and everything the agent then does goes through your [permissions](permissions.md) as always. A command from a
plugin that says "delete the tests" still asks before each change.

Plugins are yours, installed in your user folder: a project can't bring one, and a cloned repository can't install one.

## Commands
| command | what it does |
|---|---|
| `/plugin` | the installed plugins: on or off, version, what each adds, and its options with your values |
| `/plugin install PATH` | copy a plugin folder into `~/.harness/plugins/NAME` and turn it on |
| `/plugin install URL` | the same from a git repository (`https://...`, `git@...`, or anything ending in `.git`): it is cloned with `git clone --depth 1`, without its history |
| `/plugin install --force PATH\|URL` | replace an installed plugin of the same name (your option values are kept) |
| `/plugin config NAME` | its options: each one's type, your value, the default and what it means |
| `/plugin config NAME KEY VALUE` | set an option |
| `/plugin enable NAME`, `/plugin disable NAME` | turn it on or off (off: nothing of it is loaded; your values are kept) |
| `/plugin remove NAME` | delete it and your values |

A change takes effect at once: the commands, skills, agents and styles are read again, and the system prompt is rebuilt.

In the [web UI](web-ui.md), **Settings** has a **Plugins** section: each plugin with an on/off switch and a form for its options, and a box
to install one by path or address. It sends the same commands.

## Options
Each option has a type, and a value you set must fit it:

| type | values |
|---|---|
| `choice` | one of the listed choices |
| `boolean` | `true` or `false` (also `yes`/`no`, `on`/`off`, `1`/`0`) |
| `number` | a number |
| `string` | one line of at most 200 characters |

Your values are kept in `~/.harness/plugins.json`. They become part of what the model reads, so **a value that looks like a secret (an API
key, a token) is refused**: keep those in environment variables.

## Where it goes, and who wins
```text
~/.harness/plugins/NAME/          the plugin's files, as installed
~/.harness/plugins.json           which plugins are on, and your values
```
Names are shared with everything else, and **yours win**: a plugin never replaces a built-in command, agent or style, nor anything in your
`~/.harness` folders or the project's `.harness`. A clash is skipped with a warning at start (`plugin greeter can't replace the skill 'greet'
(user's); skipped`).

## Two examples
`examples/plugins/` in the repository has two plugins to install and read:

- **code-review**: `/review [file or focus]` reviews your uncommitted changes (`git diff`) or a file, and reports at most `max_findings`
  findings. Options: `language` (any, python, cpp, javascript, typescript, rust, go, java), `strictness` (gentle, normal, strict),
  `max_findings` (5).
- **cpp-helper**: a `cpp` skill (how to write, build and fix C++ with your compiler and standard; the agent loads it when a task is about
  C++) and `/cpp-test FILE.cpp` (build, run, fix). Options: `compiler` (g++, clang++, cl), `standard` (c++17, c++20, c++23), `warnings`
  (true).

To write your own, see [writing a plugin](../reference/writing-a-plugin.md).

## Safety
- Read a plugin before you install it, as you would read a script before running it. Its text becomes instructions: a plugin could tell the
  agent to do things you didn't ask for. Your permissions still apply to every step.
- Installing copies plain files only. A plugin with a link in it (which could copy a file from elsewhere on your computer into a skill the
  agent reads) is refused, and so is one over 300 files or 2 MB.
- `git clone` downloads from the address you give. Only install from people you trust.
