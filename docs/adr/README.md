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
