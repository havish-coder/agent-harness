# Contributing

Thanks for your interest! This is a personal learning project, but issues and pull requests
are welcome.

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate             # macOS/Linux: source .venv/bin/activate
pip install -e ".[tui,web,dev]"
ollama pull qwen3:4b-instruct      # only needed for live runs; tests don't need a model
```

## Before you open a pull request
Every change must pass the same checks a release does:

```bash
pytest                       # all tests, no model or network needed
ruff check .                 # lint
python scripts/check_docs.py # no broken links in the docs
```

## Definition of done
A change is finished when:
1. **Code and tests**: new behaviour has tests; `pytest` and `ruff check .` pass.
2. **Docs**: the user guide and reference describe the change; anything users notice gets a
   line under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md).
3. **Decisions**: if you chose between real alternatives (a format, a dependency, a security
   trade-off), add an [ADR](docs/adr/README.md).
4. **Live check**: if the change affects how the model behaves, try it on a real model and
   say what you saw in the pull request.

## Style
- Python 3.10, type hints on public functions, docstrings that say *why* as well as *what*.
- The agent core (`harness/` outside `tui/` and `web/`) depends only on the standard library
  and `httpx`. No agent frameworks. New runtime dependencies need an ADR.
- Tools return text written for the model to read: short, specific, and with a hint about
  what to do next when something fails.
- Commit messages: imperative mood, first line under 72 characters.
