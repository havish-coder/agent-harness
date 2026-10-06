# 0004. Generate tool schemas from type hints and docstrings

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Every tool needs a JSON Schema describing its arguments, because that is all the model sees.
In v0.1 schemas were written by hand next to the function. The two drift apart: rename an
argument in the function and the schema still advertises the old name, and the model's calls
fail with `unexpected keyword argument`.

## Options
1. **Hand-written JSON Schema** next to each function: explicit, but duplicated and drifts.
2. **A validation library** (pydantic, as the Python counterpart of zod): rich validation,
   but a heavy runtime dependency in the core, against [ADR 0002](0002-no-agent-frameworks.md).
3. **Derive from type hints + docstring** with a small decorator: one source of truth, stdlib
   only, limited to the types we support.

## Decision
Option 3. `@tool` reads the signature (`inspect`, `typing.get_type_hints`) and a Google-style
docstring (`Args:` section). Supported types: `str`, `int`, `float`, `bool`, `dict`,
`list[X]`, `Literal[...]` and `X | None`. Anything else, a missing hint or a missing docstring
**raises `TypeError` when the module is imported**, not when the model calls the tool.

## Consequences
- Renaming an argument updates the schema automatically.
- A tool can't exist without a description: the docstring is the model's manual.
- Unions of several types are rejected on purpose; small models handle them poorly.
- Complex nested argument objects aren't supported. If a tool needs one, it can pass a
  hand-written `parameters` to `Tool(...)` directly.
