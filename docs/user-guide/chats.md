# Chats and projects

Every conversation you have is saved, so closing the terminal doesn't end it. A **project** is a folder you run the agent in
(`--workspace`); a **chat** is one conversation in it. A project has as many chats as you like, and each keeps its own history.

```bash
harness --workspace my-app            # a new chat (the previous ones are saved)
harness --workspace my-app -c         # carry on with the most recent chat
harness --workspace my-app -r cart    # carry on with the chat whose title has "cart" in it
harness --workspace my-app -r         # choose from a list
```

## In a chat
| Command | |
|---|---|
| `/chats` | the saved chats of this project, newest first: number, when you last used it, how many messages, its title. `*` marks the one you are in |
| `/resume 2` | go back to chat number 2. A word from its title (`/resume cart`) or the start of its id works too, if only one chat matches |
| `/reset` (`/new`, `/clear`) | start a new chat. The one you were in stays saved |
| `/rename Fix the cart` | name this chat. Until you do, its title is your first message |
| `/fork` | copy this chat into a new one and carry on there; the original stays as it was. `/fork try the other approach` names the copy |

A chat is created when you send its first message, so starting the app and quitting leaves nothing behind.

## What comes back when you resume
The conversation is rebuilt exactly as it stood: your messages, the agent's replies, its tool calls and results, results that had been
[cleared to make room, and summaries](context.md), and the title. The agent then goes on in the same saved chat.

What does **not** come back:
- **The system prompt**: you get today's (the date, the git state, the file listing, your current settings), not the old one.
- **Which files the agent has read.** Before it edits a file it must read it again, which is the safe direction.
- **The model server's memory of the conversation**, once it has forgotten it (a local server does after a few minutes idle, a hosted one after its cache
  time-out). The first reply after that reads the whole conversation again, which takes a few seconds on a local model. Resuming within a minute or two of
  quitting usually still finds it cached.
- **A step that never finished.** If the terminal was closed while the agent was in the middle of a tool call, the unfinished call is dropped
  (you are told how many messages), because the model can't continue from a call with no result.
- **Permissions you granted for the session** (`/permissions allow ...`, "always allow") and `/mode` changes: they are decisions about *this* run.

What **does** come back, on purpose: if the chat had read **untrusted content** (a web page, or files from a folder you don't trust), it still counts as having read it,
so broad approvals keep asking ([untrusted content](untrusted-content.md)). Resuming can't be used to start clean after a page told the agent something.

## Where chats are kept
```text
~/.harness/projects/<folder name>-<8 hex digits>/chats/<date>-<time>-<hex>.jsonl
```
(Set `HARNESS_HOME` to use another folder.) They are in **your** folder, not in the project, so they are never committed by accident, and each is a plain file of
JSON lines that you can read, search or delete. Each line is one thing that happened, and nothing is ever rewritten, so a crash can only damage the line being written
and that line is skipped when the chat is resumed.

- **Secrets are hidden by shape** before anything is written ([secrets and the audit log](audit-and-limits.md)), including ones you typed into a message. The conversation in
  memory still has them; the file doesn't.
- **The files are private** to your user where the system allows (mode 600 on Linux and macOS; on Windows your folder's own permissions apply).
- **They hold what the agent read.** File contents and command output are in them, so treat the folder like your code. Delete one with `rm`, or all of a project's chats by
  deleting its folder.
- **Old chats are deleted** after 30 days without use (`chat_retention_days`; `0` keeps them for ever). Only the chats of the project you are running in are checked.
- **Turn it off** with `--no-save` for one run, or `"save_chats": false` in your settings. Nothing is written, and `-c` and `/chats` say so.

To go **back** inside a chat (forget the last few requests, and put the files they changed back), see [undo and rewind](undo.md): `/rewind` is recorded in the chat, so a resumed chat is rewound too.

One chat should be open in one place at a time. Two terminals resuming the same chat would each add their own messages to the same file.
(Different chats, or the same project from two windows, are fine.)

## Settings
| Setting | Default | |
|---|---|---|
| `save_chats` | `true` | keep conversations on disk. Not accepted from project settings |
| `chat_retention_days` | `30` | delete chats of the project not used for this many days; `0` keeps them. Not accepted from project settings |
