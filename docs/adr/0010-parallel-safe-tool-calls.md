# 0010. Run consecutive concurrency-safe calls on threads

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Models can return several tool calls in one reply; `qwen3:4b-instruct` did so in 4 of 7
tool-calling replies in our measurements. Running them one by one is simplest. Running them
together is faster for slow tools (network, sub-agents, big searches), but unsafe for tools
that change things: two edits to one file, or an edit and a read of the same file, depend on
order, and two approval prompts can't be shown at once.

## Options
1. **Always sequential**: simple and safe; slow tools add up.
2. **Everything in parallel**: fastest; races, interleaved approvals, order-dependent results.
3. **Partition by the fail-closed `concurrency_safe` flag**: consecutive safe calls form a
   batch run on threads; every other call runs alone, in order.
4. **asyncio**: efficient for I/O, but every tool and provider would have to become async.

## Decision
Option 3, using a `ThreadPoolExecutor` (up to 8 workers) per batch. Results are appended in
the model's order and events are emitted from the main thread.

## Consequences
- Tools marked `concurrency_safe` must be thread-safe.
- Approvals never overlap: a call that may need approval is never in a multi-call batch.
- For today's local file tools the gain is negligible (one measured run: 24.2 s in the model,
  9 ms in tools); the benefit arrives with slow tools.
- A cancelled turn (Ctrl+C) doesn't stop worker threads already running; they are read-only
  and finish quickly, and their results are discarded by the rollback.
