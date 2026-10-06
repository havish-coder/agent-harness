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
