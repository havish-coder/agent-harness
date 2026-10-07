# Slash commands

Type `/` and press Tab to see them. Commands either do something in the app straight away, or
send a ready-made request to the model.

## Built-in
| Command | Does |
|---|---|
| `/help` | list all commands, including your own |
| `/reset` (`/clear`) | forget the conversation and start fresh |
| `/cost` | tokens and cost so far, per model |
| `/config` | the settings in effect and which file each came from |
| `/model [name]` | show the model, or switch to another one; the conversation is kept |
| `/tools` | the tools the agent can use, and which ones only read |
| `/style [name]` | list [output styles](styles-and-status.md), or switch to one |
| `/mode [name]` | show the [permission modes](permissions.md), or switch to one |
| `/trust`, `/untrust` | trust this folder, or stop: [untrusted content](untrusted-content.md) |
| `/context` | where the conversation's tokens go, against the model's window ([details](context.md)) |
| `/compact [what to keep in mind]` | replace the older conversation with a summary now, optionally telling the summary what matters ([details](context.md#summarising-the-conversation-compact)) |
| `/prompt [full]` | the system prompt's sections and what each costs; `full` prints the text the model reads ([details](context.md#the-system-prompt)) |
| `/audit [N\|verify]` | the [audit log](audit-and-limits.md): recent entries, or check the chain |
| `/limits` | what this chat has used against its [limits](audit-and-limits.md#limits) |
| `/hooks` | the [hooks](hooks.md) in your settings and whether each runs |
| `/taint [clear]` | what untrusted content this chat has read; clear it |
| `/permissions [allow\|ask\|deny\|remove RULE]` | the permission rules and where each came from; add or remove one for this session |
| `/export [md\|tex\|pdf] [file] [--last]` | save the chat or the last answer ([details](math-and-export.md)) |
| `/fix-tests [focus]` | asks the agent to run the tests, fix failures and repeat until they pass |
| `/explain @path` | asks the agent to explain a file or folder |
| `/bye` (`/exit`, `/quit`) | quit |

To send a message that starts with a slash, type two: `//etc/hosts is…` sends `/etc/hosts is…`.

## Why `/fix-tests` exists
Small models rarely check their own work unless the request tells them to (see
[the terminal guide](terminal.md#ask-for-verification)). `/fix-tests` is that instruction, written
once: run the tests, fix what fails, run them again, at most three rounds, then report.

## Your own commands
A command is a Markdown file. Its text is the request sent to the model; `$ARGUMENTS` is replaced
by whatever you type after the command, and `$1`, `$2`, ... by single words.

```markdown
---
description: Explain a file to a beginner
argument-hint: <file>
---
Explain $ARGUMENTS to someone new to programming. Go step by step and quote the lines you
are talking about.
```

Save it as `teach.md` in one of:

| Folder | Available |
|---|---|
| `~/.harness/commands/` | in every project (yours only) |
| `<workspace>/.harness/commands/` | in this project; commit the folder to share commands with others |

Then use it: `/teach @project/shop/cart.py`. `@mentions` in the arguments attach files as usual.

Rules:
- Names use lowercase letters, digits and `-` (the file name without `.md`).
- If the text has no `$ARGUMENTS` or `$1`, anything you type after the command is added at the end.
- Your user commands may replace built-in prompt commands. **Project** commands can never replace a
  built-in command: a repository you cloned can't change what `/reset` or `/help` does.
- A command only sends text to the model. Anything the model then wants to do still goes through
  the usual [permissions](permissions.md).
