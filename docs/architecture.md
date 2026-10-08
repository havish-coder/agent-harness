# Architecture

This page explains how Agent Harness works inside: the parts, how a request flows through
them, and the rules that keep them separate. It describes the current release; each release
updates it.

## The big picture

```mermaid
flowchart LR
    U[User] -->|types| CLI["Terminal app<br/>harness/cli.py + tui/"]
    CLI -->|run| A["Agent loop<br/>harness/agent.py"]
    A -->|messages + tool schemas| P["Provider<br/>harness/providers/"]
    P -->|HTTP| M[(Model server<br/>Ollama)]
    A -->|tool calls| T["Tools<br/>harness/tools/"]
    T -->|read| W[(Workspace folder)]
    A -.->|events| CLI
```

| Part | Responsibility | Knows about |
|---|---|---|
| **Terminal app** | reading input, printing answers and events | the agent, the event names |
| **Agent loop** | calling the model, running tools, keeping the history | the provider interface, tools |
| **Provider** | translating between our messages and one vendor's API | one model server |
| **Tools** | doing things in the workspace, returning text | the workspace |

The arrows only go one way. The agent loop never prints and never imports the terminal app;
providers never see tools' code; tools never see messages. This is what lets the same agent
run in a terminal today and in a web server later.

## A request, step by step

```mermaid
sequenceDiagram
    participant U as User
    participant A as Agent
    participant P as Provider
    participant T as Tool
    U->>A: "How many TODOs are in my notes?"
    A->>P: chat(history, tool schemas)
    P-->>A: Reply(tool_calls=[read_file(notes.txt)])
    A->>T: read_file(path="notes.txt")
    T-->>A: "TODO: buy milk ..."
    A->>P: chat(history + tool result)
    P-->>A: Reply("There are 3 TODOs ...")
    A-->>U: answer
```

The loop repeats *call the model → run the requested tools → append the results* until the
model answers without asking for tools, or until the step limit (default 10) is reached.

## Streaming

A provider may implement `stream()` in addition to `chat()`: a generator that yields pieces of
text (`TextDelta`, `ThinkingDelta`) as the model produces them, and the complete `Reply` last.
The agent forwards each piece as an event, so interfaces can show the answer as it's written.
Closing the generator (on Ctrl+C or any error) closes the HTTP connection, which makes the
model server stop generating. See [ADR 0013](adr/0013-streaming-generators.md).

```mermaid
sequenceDiagram
    participant A as Agent
    participant P as Provider.stream()
    participant UI as Interface
    A->>P: iterate
    P-->>A: TextDelta("Hel")
    A-->>UI: text_delta "Hel"
    P-->>A: TextDelta("lo")
    A-->>UI: text_delta "lo"
    P-->>A: Reply(complete message, usage)
    A-->>UI: model_reply
```

## Retries

Interfaces wrap the provider in `RetryingProvider`
([`harness/providers/retry.py`](../harness/providers/retry.py)). It retries errors marked
`retryable` (connection failures, timeouts, 408, 409, 429, 5xx, overloaded) with exponential
backoff and jitter, honours `Retry-After`, stops at a total waiting budget, and can hand the
call to a fallback provider. A stream is retried only if it failed before its first piece of
text. The agent loop never sees a retried failure. See
[ADR 0016](adr/0016-retry-policy.md).

## Running one tool call

Every call the model makes goes through the same checks, in this order. Each "no" becomes a
text result the model reads on its next step; nothing here can crash the loop.

```mermaid
flowchart TD
    C[tool call from the model] --> K{known tool?}
    K -- no --> E1["Error: unknown tool ... Available tools: ..."]
    K -- yes --> V{arguments valid?}
    V -- no --> E2["Error: invalid arguments ... Expected: signature"]
    V -- yes --> TC{tool's own check<br/>passes?}
    TC -- no --> E3["Error from the tool, e.g.<br/>read the file first"]
    TC -- yes --> P{"permissions decide<br/>(rules, protected paths, mode)"}
    P -- deny --> E4["Error: not allowed: reason"]
    P -- allow --> RUN[run the tool]
    P -- ask --> A{you approve?}
    A -- no --> D[denial message]
    A -- "yes / always" --> RUN
    RUN --> T[cap the result length] --> OUT[tool result]
```

The checks live in [`harness/tools/registry.py`](../harness/tools/registry.py) (lookup,
validation, running, truncation) and [`harness/agent.py`](../harness/agent.py) (the tool's
own `check`, then the permission decision and, if it says *ask*, your answer). The decision is
made by `Permissions.decide()` in [`harness/security/permissions.py`](../harness/security/permissions.py):
deny rules first, then protected paths and ask rules, then the mode, then allow rules, then
read-only tools; anything left asks ([ADR 0026](adr/0026-permission-modes-and-rules.md)). It is
plain code, so the same call always gets the same answer ([ADR 0024](adr/0024-deterministic-security-decisions.md)).
A tool's check runs before the decision so you are never asked to approve a call that would fail.

Content that comes back from tools is handled before the model sees it: results from tools that carry
outside text (`read_file`, `grep`, `run_shell`) are wrapped in `<untrusted>` tags and recorded in a
**taint** list that the permission decision consults ([`harness/security/taint.py`](../harness/security/taint.py),
[ADR 0028](adr/0028-fence-and-taint-untrusted-content.md)).

For `run_shell`, the decision first *reads* the command ([`harness/security/shell.py`](../harness/security/shell.py),
[ADR 0027](adr/0027-read-commands-and-scrub-secrets.md)): it splits `a && b | $(c)` into the commands
it would run and notes their risks, so deny rules can find a command wherever it hides and allow rules
must cover every command in the line. The command then runs with secret environment variables removed
([`harness/security/secrets.py`](../harness/security/secrets.py)).

Paths are confined before any of this matters: every file tool turns its path argument into a
real location with `Workspace.path()` in [`harness/workspace.py`](../harness/workspace.py), which
resolves `..`, absolute forms and links and refuses anything outside the workspace (the path jail,
[ADR 0025](adr/0025-path-jail.md)). Since the tools' checks and bodies both call it, a call that
leaves the workspace fails at the check, before you're asked.

## Several calls in one reply

A model may ask for several tools at once (in our measurements, 4 of 7 tool-calling replies
did). The agent splits them into **batches**, in order: consecutive calls whose tools are
*concurrency-safe* share a batch and run on threads (up to 8 at a time); any other call is a
batch of its own. Results always go back in the order the model asked, and events are
emitted from the main thread.

```mermaid
flowchart LR
    R["reply: read a, read b, edit c, read d"] --> B1["batch 1: read a + read b<br/>(parallel)"]
    B1 --> B2["batch 2: edit c<br/>(alone, may ask approval)"]
    B2 --> B3["batch 3: read d"]
```

Every call in a batch is checked and decided on the main thread before the batch runs, so
questions to you never overlap and never come from a worker thread. See
[ADR 0010](adr/0010-parallel-safe-tool-calls.md).

## Key design rules

### 1. One message format inside, many outside
Every provider speaks its own JSON dialect. Inside the harness there is exactly one format,
defined in [`harness/messages.py`](../harness/messages.py): `Message`, `ToolCall`, `Reply` and
`Usage`. Each provider adapter translates in both directions. See
[ADR 0003](adr/0003-provider-neutral-message-model.md).

### 2. Tool errors are results, not crashes
If a tool fails, or the model calls a tool that doesn't exist or passes wrong arguments, the
error becomes the tool's result text. The model reads it on its next step and usually fixes
its own mistake.

### 3. A turn either completes or never happened
If anything goes wrong mid-turn (the server fails, the user presses Ctrl+C), the agent
deletes every message the turn added. The history therefore never ends with a tool request
that has no result, which some APIs reject.

### 4. The loop reports, it doesn't print
The agent emits events through an `on_event(kind, data)` callback. Interfaces decide what to
show. See the [events reference](reference/events.md).

## Source layout

```
harness/
  agent.py          the agent loop: steps, tool calls, approvals, hooks, context checks, rollback
  messages.py       provider-neutral message types
  session.py        one running session: settings, workspace, provider, tools, agent, costs, UI
  cli.py            the `harness` command: flags, the input loop, command dispatch, --worktree
  commands.py       slash commands: built-in, Markdown-defined, and skills started by name
  styles.py         output styles added to the system prompt
  export.py         /export: chats as Markdown, LaTeX (pandoc) or PDF (pandoc + Tectonic)
  mentions.py       @file mentions attached to messages
  config.py         settings layers, validation, .env loading
  workspace.py      the path jail and read tracking for all file tools
  usage.py          prices and per-session cost tracking
  limits.py         per-chat limits on calls, cost, tokens and time
  audit.py          the hash-chained audit log
  hooks.py          your scripts before and after tool calls, and before a message is sent
  chats.py          saved chats: append-only logs, resume, fork
  memory.py         HARNESS.md project memory
  automemory.py     notes the agent saves for itself
  journal.py        the project's progress journal
  filehistory.py    a copy of each file before an edit tool changes it, for /undo and /rewind
  todo.py           the todo list, seeding from a numbered request, the nudge
  plan.py           plan mode's exit_plan_mode and saved plans
  ask.py            questions from the agent to the user
  agents.py         sub-agent definitions and the delegate tool
  tasks.py          commands running in the background
  skills.py         skills loaded on demand
  toolsearch.py     holding rarely used tool definitions back, and tool_search
  mcp.py            the MCP client: tools from other programs over stdio
  worktree.py       a git worktree for a session, and its cleanup
  context/          token estimates and window sizes, the system prompt's sections, clearing old results, summarising
  providers/
    base.py         the Provider interface and ProviderError
    ollama.py       Ollama adapter (/api/chat, NDJSON streaming)
    openai_compat.py  OpenAI Chat Completions adapter (SSE streaming)
    anthropic.py    Anthropic Messages adapter (content blocks, named SSE events, prompt caching)
    factory.py      make_provider(name, model, ...) for interfaces
    retry.py        RetryingProvider: backoff, Retry-After, budget, fallback
    fake.py         scripted, recording and replaying providers for tests
  tools/
    base.py         the Tool type and the @tool decorator
    registry.py     lookup, argument validation, running, result caps, held-back tools
    fs.py           list_dir, read_file, workspace_snapshot
    search.py       glob, grep
    edit.py         edit_file, write_file
    shell.py        run_shell (in the foreground or the background), task_output, task_stop
    web.py          web_fetch
  security/         permissions and rules, shell command analysis, taint and folder trust, the network guard,
                    secrets and redaction, the OS sandbox
  tui/              terminal interfaces: rich (Markdown, diffs, spinner) and plain; the line editor (prompt.py),
                    the Esc/type-ahead key watcher (keys.py), LaTeX math to Unicode (latex.py)
scripts/            setup check, the labs that measure each feature, demo rendering
tests/              unit and integration tests, recorded runs, a test MCP server
workspace/          a sample folder to try the agent on
docs/               this documentation
```
