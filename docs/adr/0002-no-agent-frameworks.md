# 0002. No agent frameworks; minimal core dependencies

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Frameworks such as LangChain, LlamaIndex or CrewAI provide agent loops, tool abstractions and
provider wrappers. They save time, but they hide the loop behind layers of abstraction, change
their APIs often, and pull in large dependency trees. The project's goal is an agent whose
every behaviour can be read, tested and secured.

## Options
1. **Build on a framework**: fast start; behaviour depends on code we don't control.
2. **Use vendor SDKs** (openai, anthropic): official, but one SDK per provider, each with its
   own types.
3. **Write the core ourselves** on the standard library plus one HTTP client.

## Decision
The agent core (everything in `harness/` except the user interfaces) depends only on the
Python standard library and `httpx`. User interfaces may use UI libraries: `rich` and
`prompt_toolkit` for the terminal, `fastapi` and `uvicorn` for the web. These live in optional
dependency groups (`tui`, `web`). Any new runtime dependency needs its own ADR.

## Consequences
- The whole agent stays small enough to read and audit.
- We implement things frameworks give for free: retries, streaming parsers, schema
  generation. Each is tested.
- Provider wire formats must be tracked by hand when vendors change them.
