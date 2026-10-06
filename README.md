# Agent Harness

**A coding agent you can read end to end.** Agent Harness is a Claude Code-style AI agent
written from scratch in Python, without agent frameworks. It talks to a local model through
[Ollama](https://ollama.com) or to a cloud API, inspects and edits files, runs commands, and
explains every step it takes.

> **Status: v0.3, pre-release.** The agent reads, searches and edits code and runs commands,
> asking your approval (with a diff) before anything changes. It streams its answers and runs
> on Ollama, Claude or any OpenAI-compatible service, with retries, settings files and cost
> tracking. Security hardening, memory, sub-agents and a web UI are on the [roadmap](#roadmap).
> See the [changelog](CHANGELOG.md) for what changed in each release.

---

## Why
Most agent products are either closed or built on large frameworks that hide the loop. This
project keeps the whole agent small enough to read: the core is the Python standard library
plus [`httpx`](https://www.python-httpx.org/). Every design decision is written down as an
[architecture decision record](docs/adr/).

## Features
| | Feature | Since |
|---|---|---|
| ✅ | Agent loop with step limit, errors fed back to the model, and rollback on failure | v0.1 |
| ✅ | Provider-neutral message model; Ollama adapter | v0.1 |
| ✅ | Workspace file tools (`list_dir`, `read_file`) and a workspace snapshot in the prompt | v0.1 |
| ✅ | Terminal chat with live tool-call display and token counts | v0.1 |
| ✅ | Tools defined as plain Python functions; schemas generated from type hints | v0.2 |
| ✅ | Argument validation with errors the model can act on; capped results | v0.2 |
| ✅ | Paged `read_file`, `glob` and `grep` | v0.2 |
| ✅ | `edit_file` / `write_file`: exact edits, only after reading, never on stale files | v0.2 |
| ✅ | `run_shell`: bash (or PowerShell), timeouts, real exit codes | v0.2 |
| ✅ | Approval before every change, with a diff; `a`lways per tool | v0.2 |
| ✅ | Safe tool calls run in parallel | v0.2 |
| ✅ | Recorded real runs replayed as regression tests | v0.2 |
| ✅ | Streaming answers; Ctrl+C really stops the model | v0.3 |
| ✅ | Providers: Ollama, Anthropic (with prompt caching), any OpenAI-compatible API | v0.3 |
| ✅ | Automatic retries with backoff; fallback model | v0.3 |
| ✅ | Layered settings files; API keys only from the environment or `.env` | v0.3 |
| ✅ | Token, cache and cost tracking per turn and per session | v0.3 |

## Quickstart
Requirements: Python 3.10+, [Ollama](https://ollama.com/download), about 3 GB of disk.

```bash
ollama pull qwen3:4b-instruct
git clone https://github.com/havish-coder/agent-harness.git
cd agent-harness
python -m venv .venv
.venv\Scripts\activate            # Windows; on macOS/Linux: source .venv/bin/activate
pip install -e ".[tui,dev]"
harness --workspace workspace
```

Cloud models work too, e.g. `harness --provider anthropic` with `ANTHROPIC_API_KEY` set; see
[choosing a model](docs/user-guide/models.md).

Then ask something like *"How many TODOs are in my notes?"*. Full walkthrough:
[Getting started](docs/getting-started.md).

## Documentation
| | |
|---|---|
| [Getting started](docs/getting-started.md) | install, first run, first task |
| [User guide](docs/user-guide/) | how to use each feature |
| [Reference](docs/reference/) | CLI flags, tools, events |
| [Architecture](docs/architecture.md) | how the agent works inside |
| [Decision records](docs/adr/) | why it is built this way |
| [Security](SECURITY.md) | the security model and how to report issues |

## Roadmap
| Release | Theme |
|---|---|
| v0.4 | A polished terminal app: rich rendering, input history, slash commands, status line |
| v0.5 | Security: path jail, permission modes and rules, shell hardening, hooks, audit log |
| v0.6 | Context: token budgets, compaction, sessions, project and auto memory, undo |
| v0.7 | Workflows: todo list, plan mode, sub-agents, skills, background tasks, MCP |
| v0.8 | Web UI with streaming, approvals and settings |
| v1.0 | Evals, tracing, packaging, CI |

## Development
```bash
pip install -e ".[tui,web,dev]"
pytest            # tests
ruff check .      # lint
```
See [CONTRIBUTING.md](CONTRIBUTING.md). The project started as a course; lessons 00-07 are in
[`course/`](course/README.md).

## License
[MIT](LICENSE)
