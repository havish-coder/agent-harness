# 0013. Stream with a generator per model call, reported through events

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
A reply from `qwen3:4b-instruct` takes about 10 seconds for 180 tokens on the development
machine, but its first token is ready after 0.1-0.5 s. Without streaming the user stares at
nothing for those 10 seconds. Streaming touches every layer: the HTTP client, the provider,
the loop and each interface.

## Options
1. **No streaming**: simplest; poor perceived latency.
2. **Callback passed into the provider** (`chat(..., on_text=...)`): small change, but providers
   then call into UI code, and cancellation is awkward.
3. **Async generators everywhere** (`async for`): idiomatic for I/O, but every tool, provider
   and interface must become async.
4. **A synchronous generator per model call**: `stream()` yields text pieces, then the `Reply`;
   the agent turns pieces into events.

## Decision
Option 4. `stream()` is optional (`StreamingProvider` protocol); providers without it keep
working through `chat()`. The agent emits `text_delta` and `thinking_delta`, then `model_reply`.
Leaving the generator early closes the HTTP connection.

## Consequences
- Interfaces get text immediately (measured: first token 0.12-0.5 s versus 9.7 s for the whole
  reply) while the loop and the tools stay synchronous.
- Cancelling really stops the model: after abandoning a long stream, the next request answered
  in 0.79 s; with the first stream left running, it waited 45.8 s, because Ollama serves one
  request at a time.
- Tool calls are only acted on once the reply is complete; starting tools mid-stream is a
  possible later optimisation.
