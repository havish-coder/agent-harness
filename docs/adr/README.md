# Architecture decision records

An ADR records one significant decision: the context, the options, what we chose and what it
costs. ADRs are never edited after they are accepted; a later ADR can *supersede* one.

Copy [the template](template.md) to `NNNN-short-title.md` with the next number.

| # | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-no-agent-frameworks.md) | No agent frameworks; minimal core dependencies | Accepted |
| [0003](0003-provider-neutral-message-model.md) | One provider-neutral message model | Accepted |
| [0004](0004-tool-schemas-from-type-hints.md) | Generate tool schemas from type hints and docstrings | Accepted |
| [0005](0005-approve-every-non-read-only-call.md) | Ask before every tool call that isn't read-only | Accepted |
| [0006](0006-paged-numbered-file-reads.md) | Read files in numbered, bounded pages | Accepted |
| [0007](0007-pure-python-search.md) | Implement search in pure Python | Accepted |
| [0008](0008-exact-string-edits.md) | Edit files by exact string replacement, only after reading them | Accepted |
| [0009](0009-shell-tool.md) | A single shell tool, PowerShell on Windows | Superseded by 0011 |
| [0010](0010-parallel-safe-tool-calls.md) | Run consecutive concurrency-safe calls on threads | Accepted |
| [0011](0011-prefer-bash-no-cwd.md) | Prefer bash on Windows too, and drop the `cwd` argument | Accepted |
| [0012](0012-record-replay-tests.md) | Test agent behaviour with recorded model runs | Accepted |
| [0013](0013-streaming-generators.md) | Stream with a generator per model call, reported through events | Accepted |
| [0014](0014-openai-compatible-adapter.md) | One OpenAI-compatible adapter for cloud models; keys only from the environment | Accepted |
| [0015](0015-anthropic-adapter-and-caching.md) | A native Anthropic adapter that adds prompt-cache markers | Accepted |
| [0016](0016-retry-policy.md) | Retry temporary provider failures in a wrapper, never mid-text | Accepted |
| [0017](0017-layered-json-settings.md) | Layered JSON settings; secrets only in the environment | Accepted |
| [0018](0018-cost-tracking.md) | Track cost from token counts with a small, dated price table | Accepted |
| [0019](0019-rich-terminal-ui.md) | Render the terminal with rich, keep a plain fallback | Accepted |
| [0020](0020-key-watcher-thread.md) | Watch the keyboard on a thread during agent turns | Accepted |
| [0021](0021-markdown-prompt-commands.md) | Slash commands: local code, or Markdown prompt templates | Accepted |
| [0022](0022-output-styles-and-status-line.md) | Output styles as system-prompt additions; status line computed per prompt | Accepted |
| [0023](0023-latex-math-and-export.md) | Our own LaTeX-to-Unicode converter for the terminal; pandoc and Tectonic for documents | Accepted |
| [0024](0024-deterministic-security-decisions.md) | Make security decisions in deterministic code; treat tool calls as untrusted input | Accepted |
| [0025](0025-path-jail.md) | Confine file tools by resolving paths, then checking containment | Accepted |
| [0026](0026-permission-modes-and-rules.md) | Decide every tool call with modes and allow/ask/deny rules, strictest first | Accepted |
| [0027](0027-read-commands-and-scrub-secrets.md) | Read shell commands before applying rules, and run them without secrets | Accepted |
| [0028](0028-fence-and-taint-untrusted-content.md) | Fence untrusted content, and stop blanket approvals once it has been read | Accepted |
| [0029](0029-web-fetch-with-an-address-guard.md) | Fetch web pages through an address guard that connects to the address it checked | Accepted |
| [0030](0030-hooks-tighten-never-loosen.md) | Hooks are user scripts that can tighten decisions, and never loosen the protected ones | Accepted |
| [0031](0031-redact-audit-and-limit.md) | Redact secrets by shape, keep a hash-chained audit log, and limit a session | Accepted |
| [0032](0032-optional-os-sandbox-for-commands.md) | Run commands in an OS sandbox where the system offers one | Accepted |
| [0033](0033-estimate-context-and-refuse-overflow.md) | Estimate the conversation's size ourselves, and refuse to send what won't fit | Accepted |
| [0034](0034-system-prompt-from-ordered-sections.md) | Build the system prompt from sections ordered by how often they change, within a budget | Accepted |
| [0035](0035-clear-old-tool-results-before-anything-else.md) | Clear old results of re-runnable tools when the window fills, before anything else | Accepted |
| [0036](0036-summarise-when-clearing-is-not-enough.md) | Summarise the older conversation when clearing is not enough, and clear only what the model has used | Accepted |
| [0037](0037-chats-as-append-only-logs-of-messages-and-operations.md) | Save each chat as an append-only log of messages and operations, and rebuild it by replaying | Accepted |
| [0038](0038-memory-files-are-instructions-only-from-folders-you-trust.md) | Read HARNESS.md files into the prompt, but as instructions only when they are the user's | Accepted |
| [0039](0039-agent-notes-record-whether-untrusted-content-was-read.md) | Let the agent save notes for itself, and record in each whether untrusted content had been read | Accepted |
| [0040](0040-a-project-journal-written-at-checkpoints.md) | Keep a fixed-section project journal, written at checkpoints and checked before it is saved | Accepted |
| [0041](0041-keep-a-copy-before-the-edit-tools-write.md) | Keep a copy of a file just before an edit tool writes it, and put it back only if nobody has touched it since | Accepted |
| [0042](0042-a-todo-list-the-harness-can-see.md) | Give the agent a todo list the harness can see, and send it back when it tries to finish early | Accepted |
| [0043](0043-plan-mode-ends-with-the-users-yes.md) | Plan mode ends only with the user's yes, through a tool that exists only in plan mode | Accepted |
| [0044](0044-let-the-agent-ask-with-limits.md) | Let the agent ask the user a question, with a counter, a label and a warning | Accepted |
| [0045](0045-sub-agents-share-permissions-not-conversations.md) | Sub-agents share the parent's permissions, taint and limits, and not its conversation | Accepted |
| [0046](0046-background-commands-are-the-same-tool.md) | Run a command in the background with a parameter of `run_shell`, not with a second tool | Accepted |
| [0047](0047-skills-load-on-demand-and-are-text-only.md) | Skills are loaded on demand, started by name, and are text only | Accepted |
| [0048](0048-hold-back-tool-definitions-until-the-model-asks.md) | Hold back the definitions of rarely used tools until the model asks for them | Accepted |
