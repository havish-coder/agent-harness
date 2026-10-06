# 0003. One provider-neutral message model

- **Status:** Accepted
- **Date:** 2026-10-06 (decision made in v0.1)

## Context
Ollama, OpenAI-compatible servers and Anthropic each represent conversations differently:
tool calls in different fields, tool results as separate messages or as content blocks,
arguments as objects or JSON strings. If the agent loop handled these differences, every
provider would touch the loop.

## Options
1. **Use one vendor's format everywhere** (e.g. OpenAI's) and convert the others to it.
2. **Our own minimal format**, with an adapter per provider.

## Decision
Define our own types in `harness/messages.py` (`Message`, `ToolCall`, `Reply`, `Usage`, and a
`stop_reason` of `end`, `tool_calls` or `max_tokens`). Each provider implements
`chat(messages, tools) -> Reply` and translates in both directions. Nothing outside
`harness/providers/` sees vendor JSON.

## Consequences
- Adding a provider means writing one adapter, never touching the loop.
- The format must cover the union of what providers need (for example, tool-call IDs, which
  some providers require and others ignore).
- Features only one vendor has (e.g. prompt caching) need a neutral way to express them, or
  stay inside that vendor's adapter.
