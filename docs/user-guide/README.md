# User guide

How-to guides for using Agent Harness. Start with [Getting started](../getting-started.md) if
you haven't installed it yet.

- [Using the terminal app](terminal.md): starting, asking, cancelling, commands
- [Choosing a model and provider](models.md): local or cloud, API keys
- [The workspace and its boundary](workspace.md): which files the agent can use, and allowing more folders
- [Permissions: modes and rules](permissions.md): what runs without asking, what asks, what's refused
- [Reading web pages](web.md): `web_fetch`, where it can connect, and your own servers
- [Project memory: HARNESS.md](memory.md): notes the agent reads every time; whose words they count as
- [The todo list](todo.md): a checklist for jobs with several parts; the agent is sent back when it stops early
- [Plan mode](plan-mode.md): the agent looks and proposes; nothing changes until you say yes
- [Questions from the agent](ask-user.md): it asks instead of guessing, at most three times
- [Sub-agents](sub-agents.md): hand a job to a fresh agent and get back only its report
- [Commands in the background](background-tasks.md): start a long command, keep working, hear when it ends
- [Skills](skills.md): instructions loaded when they are needed, started by name
- [Tool search](tool-search.md): rarely used tools are described only when the agent asks for them
- [MCP servers](mcp.md): tools from other programs; what they may do, and why their results are untrusted
- [Undo and rewind](undo.md): put back what the agent changed, or go back to before a request
- [The progress journal](journal.md): a new chat starts from where the last one stopped
- [Notes the agent saves for itself](auto-memory.md): `remember`, what asks, and notes saved after reading something you don't trust
- [Chats and projects](chats.md): every conversation is saved; `-c` and `/resume` carry on, `/fork` copies
- [The context window](context.md): what fills it, `/context`, and what happens when it is full
- [The command sandbox](sandbox.md): confine what commands can write (Linux, macOS)
- [Secrets, the audit log and limits](audit-and-limits.md): what's hidden from the model, what is recorded, what stops a runaway chat
- [Hooks](hooks.md): your own scripts before and after tool calls, and before a message is sent
- [Untrusted content and folder trust](untrusted-content.md): files and web pages that may hold instructions for the agent
- [Configuration](configuration.md): settings files, layers, `.env` for keys
- [Slash commands](commands.md): built-in commands and writing your own
- [Output styles and the status line](styles-and-status.md): how the agent writes, and what's shown under the prompt
- [Math and PDF export](math-and-export.md): LaTeX math in answers, `/export` to Markdown, LaTeX and PDF
