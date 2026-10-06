# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version
is below 1.0, minor releases may contain breaking changes.

## [Unreleased]

### Added
- Professional documentation set: README, getting started, user guide, reference,
  architecture, decision records (ADR 0001-0003), contributing and security policies.
- MIT license.
- Optional dependency groups: `tui`, `web`, `dev` (pytest, ruff), and ruff configuration.
- `scripts/check_docs.py`: fails if any relative link in the docs is broken.

## [0.1.0] - 2026-10-05

### Added
- Agent loop with two stop conditions (final answer, step limit), tool errors returned to
  the model as text, and rollback of a failed or cancelled turn.
- Provider-neutral message model (`Message`, `ToolCall`, `Reply`, `Usage`).
- Ollama provider adapter, including a fix for reasoning text leaking from thinking models.
- `list_dir` and `read_file` tools bound to a workspace folder, and a workspace snapshot in
  the system prompt.
- Terminal chat (`harness`) with tool-call display, `/reset`, `/bye` and per-turn token counts.

[Unreleased]: https://github.com/havish-coder/agent-harness/compare/lesson-07...HEAD
[0.1.0]: https://github.com/havish-coder/agent-harness/releases/tag/lesson-07
