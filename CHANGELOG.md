# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version
is below 1.0, minor releases may contain breaking changes.

## [Unreleased]

## [0.2.0] - 2026-10-06

### Added
- Professional documentation set: README, getting started, user guide, reference,
  architecture, decision records (ADR 0001-0003), contributing and security policies.
- MIT license.
- Optional dependency groups: `tui`, `web`, `dev` (pytest, ruff), and ruff configuration.
- `scripts/check_docs.py`: fails if any relative link in the docs is broken.
- `@tool` decorator: tool schemas are generated from type hints and docstrings (ADR 0004).
- Tool safety metadata: `read_only`, `concurrency_safe`, `destructive`, all defaulting to the
  unsafe value; flags may depend on the call's arguments.
- Developer guide: [Writing a tool](docs/developer-guide/writing-tools.md).
- Tool registry: unknown tools, missing/unknown/mistyped arguments and invalid choices are
  reported to the model with the expected signature; quoted numbers and booleans
  (`"30"`, `"true"`) are accepted; `null` for an optional argument means "use the default".
- Approval: every tool call that isn't read-only asks first (`y` / `n` / `a`lways); `--yes`
  approves everything. Without an approver such calls are refused (ADR 0005).
- `agent.stop_reason`: `completed`, `max_steps`, `max_tokens`, `cancelled` or `error`.
- `tool_denied` event.

- `read_file` reads in pages: `offset` (negative = from the end) and `limit`, numbered lines,
  a header saying which lines were returned and where to continue, and clear handling of
  empty, binary, non-UTF-8 and missing files (ADR 0006).
- `Workspace`: one object resolves every tool path and remembers what the model has read.
- `glob` and `grep` tools (pure Python, ADR 0007): name patterns, regex search with context,
  `files`/`count` modes, plain-text fallback for invalid patterns, capped output.
- Sample code project in `workspace/project` (a small cart library with a failing test).
- System prompt tells the model to grep for a likely word to find definitions.
- `edit_file` (exact, unique string replacement) and `write_file` (create or overwrite), both
  refusing files the model hasn't read or that changed since (ADR 0008); unified diffs in
  results and approval prompts; CRLF files and copied line numbers handled.
- Tool hooks: `check` (runs before approval) and `preview` (shown when approving).
- `harness.tools.default_tools(ws)`: the standard tool set.
- `run_shell` tool (ADR 0011): bash wherever possible (Git for Windows' bash on Windows, then
  PowerShell), `HARNESS_SHELL` to choose; runs in the workspace root; timeout that stops the
  whole process tree, closed stdin, UTF-8 output, real exit codes from PowerShell, output that
  keeps the end.

### Changed
- Tool results longer than 8,000 characters are shortened, keeping the start and the end.
- Default `--max-steps` raised from 10 to 20: fix-and-test tasks need more steps.
- Test providers (ADR 0012): `ScriptedProvider`, and `RecordingProvider`/`ReplayProvider` for
  cassettes of real runs, with machine-specific text normalized; a recorded bug-fix run is
  replayed in the test suite. `scripts/record_cassette.py` re-records it.
- `pytest -m live` for tests against a real model (skipped by default); coverage via pytest-cov.
- When the model repeats an identical call with an identical result, the result says so.
- `glob` forgives a pattern that repeats the folder being searched (`project/a.py` in `project`).
- Message and reply serialization (`message_to_dict`, `reply_from_dict`, ...).
- Several tool calls in one reply: consecutive concurrency-safe calls run in parallel (up to 8
  threads); others run alone, in order (ADR 0010).
- The workspace snapshot in the system prompt skips folders like `.git`, `.venv` and
  `node_modules`.

## [0.1.0] - 2026-10-05

### Added
- Agent loop with two stop conditions (final answer, step limit), tool errors returned to
  the model as text, and rollback of a failed or cancelled turn.
- Provider-neutral message model (`Message`, `ToolCall`, `Reply`, `Usage`).
- Ollama provider adapter, including a fix for reasoning text leaking from thinking models.
- `list_dir` and `read_file` tools bound to a workspace folder, and a workspace snapshot in
  the system prompt.
- Terminal chat (`harness`) with tool-call display, `/reset`, `/bye` and per-turn token counts.

[Unreleased]: https://github.com/havish-coder/agent-harness/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/havish-coder/agent-harness/compare/lesson-07...v0.2.0
[0.1.0]: https://github.com/havish-coder/agent-harness/releases/tag/lesson-07
