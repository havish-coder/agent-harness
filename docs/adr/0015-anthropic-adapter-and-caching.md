# 0015. A native Anthropic adapter that adds prompt-cache markers

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Claude models are strong coding agents. Anthropic's Messages API isn't Chat Completions:
content is a list of typed blocks, the system prompt is a separate field, tool results are user
messages, and streaming uses named events. It also offers **prompt caching**: a request can mark
points (`cache_control`) up to which the processed prompt is stored; later requests that start
with the same prefix read it back at a fraction of the price and latency. An agent re-sends a
growing conversation on every step, so almost every request starts with the previous one.

## Options
1. **Use Anthropic's OpenAI-compatibility layer**: no new adapter; caching and some features
   are not available through it.
2. **A native adapter without caching**: correct but pays full price for the repeated prefix
   on every step.
3. **A native adapter that places cache markers automatically.**

## Decision
Option 3. Markers go on the last system block, the last tool definition and the last content
block of the newest message: three of the API's four allowed breakpoints. `cache=False` turns
them off. `Usage.input_tokens` reports everything the model read (uncached + cache reads +
cache writes) so totals are comparable across providers; the raw counts stay in
`provider.last_usage` for cost tracking.

## Consequences
- In a multi-step task, each request after the first mostly reads from the cache.
- Cache writes cost more than plain input, so a one-shot question gains nothing; agents rarely
  make one-shot requests.
- Tested against a fake server built from the documented formats; a live test runs only when
  `ANTHROPIC_API_KEY` is set.
