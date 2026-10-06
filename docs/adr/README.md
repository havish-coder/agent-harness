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
