# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version
is below 1.0, minor releases may contain breaking changes.

## [Unreleased]

## [0.5.0] - 2026-10-06

The security release. The agent still reads, searches, edits and runs commands, but what it may do is now decided by
code that doesn't depend on the model: the workspace boundary, permission modes and rules, command analysis,
untrusted-content handling, an address guard for web pages, hooks, redaction, an audit log, limits, and (where the
OS offers one) a sandbox. 66 attacks are tested; one known to get through on Windows, and none where a sandbox exists.
Start with [the security model](docs/security.md).

### Added
- Path jail (ADR 0025): file tools only reach the workspace. Paths are resolved first (`..`,
  absolute paths, drive letters, UNC and `\\?\` forms, symlinks and Windows junctions) and refused
  outside it; names Windows reinterprets (`a:stream`, trailing dots and spaces, device names
  like `NUL`) are refused everywhere. Links leading out are listed but never entered by
  `list_dir`, `glob`, `grep` or the workspace overview; `@mentions` outside aren't attached.
- `additional_directories` setting for folders outside the workspace the tools may use; not
  accepted from project settings.
- User guide: [the workspace and its boundary](docs/user-guide/workspace.md).
- Permission modes and rules (ADR 0026): `--mode default|accept-edits|plan|bypass`, the
  `permission_mode` setting and `/mode` to switch while working. `allow`, `ask` and `deny` rules
  per tool and per command or path (`run_shell(git status*)`, `edit_file(src/**)`) in every
  settings layer, combined strictest first: deny rules apply in every mode, and ask rules beat
  allow rules and bypass. `/permissions` lists the rules with their sources and adds or removes
  session rules. Rules naming unknown tools warn at start.
- Protected paths: writes to `.git/`, `.harness/`, `.vscode/`, `.idea/`, `.husky/`,
  `.github/workflows/`, `.pre-commit-config.yaml`, `.envrc` and `.gitattributes` always ask,
  bypass mode included.
- Shell commands are read before rules are applied (ADR 0027): split into the commands they run,
  including `$(...)`, backticks, `bash -c '...'` and `eval`, with `env`, `sudo`, `timeout` and
  `NAME=value` prefixes seen through. Deny and ask rules match any command in the line; allow
  rules must cover every one, so `run_shell(python -m pytest*)` no longer allows
  `python -m pytest; rm -rf src`. Commands run with a changed environment or a wrapper, redirections
  outside the workspace, and commands that can't be fully read (here-documents, `eval $x`, most
  PowerShell syntax) are not covered by pattern rules.
- `cd` into the workspace, `pwd`, `echo`, `printf`, `true`, `false` and `sleep` need no rule or question.
- Approval questions list the risks found in a command (deletes files, rewrites remote history, uses
  the network, installs packages, runs as administrator ...).
- Commands that write to a protected path (`>`, `cp`, `sed -i`, `tee` ...) or name one, and
  `git config` / `git -c`, ask in every mode.
- Secret environment variables (`*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `AUTH`, `COOKIE`, values
  shaped like API keys) are removed from the environment of `run_shell` commands. `shell_env_keep`
  setting to allow specific names; not accepted from project settings.
- Untrusted content (ADR 0028): file text, command output and (later) web pages reach the model inside
  `<untrusted source="...">` tags, with a standing instruction that they are data; a file can't close
  its own fence. The chat remembers the sources it has read, and after that `bypass`, `accept-edits`
  and rules for a whole tool ask instead of running; pattern rules and exact "always" answers still
  run. File text and command output count only in folders the user hasn't trusted.
- `/trust`, `/untrust` (stored in the user's settings folder, never in a project), `/taint [clear]`;
  `/reset` clears the taint. A startup notice when a broad approval is combined with an untrusted folder.
- `fence_untrusted` setting (default on; not accepted from project settings).
- `scripts/injection_lab.py` reports what a hostile instruction would have done under each mode,
  with `--fence` and `--trust`.
- `web_fetch` tool (ADR 0029): fetches one page as text. Public servers only: the address a name
  resolves to is checked (loopback, private, link-local and metadata addresses, tunnels, IPv4-mapped IPv6,
  disguised spellings such as `2130706433`), only ports 80 and 443, and the connection goes to the address
  that was checked, so DNS rebinding can't redirect it. Redirects are followed only within the same site and
  every hop is checked. 15 s, about 2 MB after decompression, text types only, proxy variables ignored.
  The first fetch from a site asks and "always" allows the site; an address with a query string asks after
  untrusted content has been read. `web_fetch` and `web_allow_local` settings; user guide *Reading web pages*.
- Hooks (ADR 0030): your own commands at `user_prompt_submit`, `pre_tool_use` and `post_tool_use`, with a JSON
  description of the call on standard input and an answer in the exit code (2 denies) or JSON. A `match` in rule
  syntax picks the calls (for commands, any command in the line). Hooks can deny or force a question; their
  `allow` only settles a routine question, never a deny rule, protected path, ask rule, plan mode or the pause
  after untrusted content; a hook that fails, times out or answers badly never allows (it asks). Project hooks run
  only in a trusted folder; `/hooks` lists them. `hooks` setting; `hook` event; `blocked` stop reason.
- Secret redaction (ADR 0031): tool results are scrubbed before the model, the screen or the log sees them
  (provider API keys, GitHub, AWS, Slack, Stripe tokens, JWTs, bearer tokens, passwords in URLs, private key
  blocks, and `NAME=value` where the name says secret); exported chats too. `redact_secrets` setting.
- Audit log: a hash-chained JSON-lines file in `~/.harness/audit/` with every decision, answer, result size,
  hook, hidden secret, model call and limit; values redacted and cut; `/audit [N|verify]`; `audit_log` setting.
- Session limits: 500 tool calls and $5 per chat by default, optional tokens and minutes; the agent stops and
  says which; `/limits`; `limits` setting; `limit` event and stop reason. A project can't change `audit_log`,
  `redact_secrets` or `limits`.
- `tool_approved`, `redacted` and `limit` events.
- OS sandbox for commands (ADR 0032): bubblewrap on Linux and `sandbox-exec` on macOS confine `run_shell` to writing
  inside the workspace, with `.git`, `.harness`, `.github/workflows` and the other protected folders read-only, and
  optionally no network. `sandbox` (`off`, `auto`, `on`; `on` refuses commands where none exists) and
  `sandbox_network` settings, never from a project. None on Windows; the wrappers are unit-tested, and run for real
  only where the tool exists.
- `scripts/attack_report.py`: the attack lab's results by threat.
- `permission` and `tool_refused` events; `model_call` is now documented.
- User guide: [permissions](docs/user-guide/permissions.md).

### Fixed
- Math written with spaces inside the dollars (`$ a \neq 0 $`, which `qwen3:4b-instruct` did in
  every answer of a live check) now renders in the terminal and in `/export` as real math instead of
  showing the dollar signs and LaTeX source. `\boxed{...}` is understood by the terminal renderer.

### Changed
- `--yes` is now `--mode bypass`: deny rules and protected paths still apply.
- Answering `a` (always) to a command now allows that exact command for the session, not every
  command; for file tools it still allows the tool. Questions say why they're asked when it's not
  routine, and don't offer `a` for protected paths.
- Project settings can't set `permission_mode` or add `allow` rules (ignored with a warning).
- Tool calls in a batch are all checked and decided before any of them runs.
- Names like `MONKEY` are no longer treated as secrets (a glued ending counts only after a prefix such as `API` or `GITHUB`).
- The test suite no longer touches the real `~/.harness`.
- The system instruction about `<untrusted>` tags and the `web_fetch` description were reworded after a measurement:
  the first versions made `qwen3:4b-instruct` decline to call the tool in some runs.
- `/tools` labels tools that aren't read-only "can change things" (they no longer all ask: see permissions).

## [0.4.0] - 2026-10-06

### Added
- Rich terminal interface (ADR 0019): answers rendered as Markdown while they stream, a spinner
  while the model thinks, one-line tool calls with a short result preview (test summaries for
  `run_shell`), highlighted diffs and commands in approval prompts. Plain mode with `--plain`,
  `NO_COLOR`, or automatically when output isn't a terminal.
- `model_call` event, emitted before each model call.
- Line editing (ADR 0020): persistent history, history search, suggestions, multi-line input
  (Esc then Enter), Tab completion of `/commands` and `@files` (needs a terminal and the `tui` extra).
- `@file` and `@folder` mentions attach content to a message and count as read.
- Esc stops a running task; keys typed while the agent works are kept for the next prompt.
- Slash commands (ADR 0021): `/help`, `/reset` (`/clear`), `/cost`, `/config`, `/model [name]`
  (switch model, keep the conversation), `/tools`, `/fix-tests`, `/explain`, `/bye`; your own
  commands as Markdown files in `~/.harness/commands/` or `<workspace>/.harness/commands/`, with
  `$ARGUMENTS` and `$1`...; project commands can't replace built-ins; `//` escapes a leading slash.
- `Session`: the running app (provider, agent, costs, UI) shared by interfaces and commands.
- Output styles (ADR 0022): `default`, `concise`, `explanatory`, `learning`, `latex`, and your own
  as Markdown files; `/style`; the `output_style` setting. Projects can't replace built-in styles.
- Status line under the prompt: model, context used (with Ollama, out of the window), session cost,
  style; the per-turn line shows the context percentage. `status_line` setting for your own
  command (JSON on stdin; never accepted from project settings).
- Math in answers (ADR 0023): LaTeX math (`$...$`, `$$...$$`, `\(...\)`, `\[...\]`) shown with Unicode
  symbols in the rich terminal, also while streaming; prices and code are left alone.
- `/export [md|tex|pdf] [file] [--last]`: the chat or the last answer as Markdown, LaTeX (pandoc) or
  PDF (pandoc + Tectonic), tools found on PATH or in `~/.harness/tools/`.
- Security documentation (ADR 0024): a threat model in `docs/security.md` (trust boundaries,
  assets, actors, threats T1-T15 and their defenses, residual risks).
- Attack lab: `tests/security/` tests each attack from the threat model as the safe outcome;
  attacks not defended yet are strict expected failures naming the release that fixes them.
  `scripts/injection_lab.py` measures how often a model follows instructions planted in files.
- `scripts/render_demo.py` renders `docs/images/demo.svg` from the recorded bug-fix run.

### Changed
- When `edit_file` or `write_file` refuses because the file wasn't read (or changed since), the
  refusal now includes the file's current content, counts as reading it, and tells the model to
  call the tool again. Small models used to read the file and then never retry the edit.
- `/fix-tests` first finds out how the project runs its tests (README, config files, the folder
  with `conftest.py` or `pyproject.toml`) and treats the code under test, not the tests, as broken.

### Fixed
- Replies are limited to `max_output_tokens` (default 4096). Ollama had no limit: a model
  stuck repeating itself kept generating for 36 minutes, blocking every other request.
- The replay tests, `render_demo.py` and `record_cassette.py` copy the workspace as committed:
  files you added to `workspace/` while trying the agent no longer break them.

## [0.3.0] - 2026-10-06

### Added
- Streaming: answers appear as they are generated (ADR 0013). Providers may implement
  `stream()`; the agent emits `text_delta` and `thinking_delta` events; `--no-stream` turns it
  off. Ctrl+C closes the connection so the model stops generating.
- `--think` for thinking models: reasoning arrives separately and is shown dimmed.
- OpenAI-compatible provider (ADR 0014): OpenAI, Groq, OpenRouter, Gemini, LM Studio, Ollama's
  `/v1`, or any compatible server with `--base-url`; streaming with tool-call fragments joined
  by index. `--provider`, `--base-url`; API keys only from environment variables.
- Anthropic provider (ADR 0015): Messages API with content blocks, grouped tool results,
  streaming of text, thinking and partial tool input, and automatic prompt-cache markers on the
  system prompt, tools and newest message. `--provider anthropic` with `ANTHROPIC_API_KEY`.
- Automatic retries (ADR 0016): exponential backoff with jitter, `Retry-After`, a 90 s budget,
  streams retried only before their first text; `--fallback-model`; retry notices in the terminal.
- Layered settings (ADR 0017): defaults, `~/.harness/settings.json`, project and local files,
  `HARNESS_*` variables, flags; `--show-config` shows each value's source; unknown keys warn
  with suggestions; secrets in settings files are refused; `.env` files for keys, with a
  warning when the workspace's `.env` isn't git-ignored; project settings that redirect
  prompts are flagged.
- Usage and cost (ADR 0018): `Usage` counts cache reads and writes (Ollama, OpenAI-compatible and
  Anthropic); per-turn cost in the terminal, `/cost`, a session summary on exit; dated prices for
  Claude models, free local models, a `prices` setting for others, unknown prices shown as such.
- User guide: [choosing a model and provider](docs/user-guide/models.md); developer guide:
  [writing a provider](docs/developer-guide/writing-a-provider.md).
- `ProviderError` carries `status`, `retryable` and `retry_after`.
- Wire-format tests for the Ollama adapter against a fake HTTP server (`httpx.MockTransport`).

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

[Unreleased]: https://github.com/havish-coder/agent-harness/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/havish-coder/agent-harness/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/havish-coder/agent-harness/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/havish-coder/agent-harness/compare/lesson-07...v0.2.0
[0.1.0]: https://github.com/havish-coder/agent-harness/releases/tag/lesson-07
