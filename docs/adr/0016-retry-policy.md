# 0016. Retry temporary provider failures in a wrapper, never mid-text

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Model servers fail temporarily. During development Ollama once answered HTTP 500 (its GPU
runner had crashed) and the same request succeeded seconds later. Cloud APIs return 429 when
rate-limited and 529 or 5xx when overloaded. Without retries each of these ends the user's turn.
Retrying blindly is also harmful: retrying a wrong API key wastes time, retrying instantly and in
lockstep makes an overload worse, and restarting a stream that has already shown text shows the
user two different answers.

## Options
1. **Retries inside each adapter**: every adapter repeats the same logic.
2. **Retries inside the agent loop**: mixes policy into the loop.
3. **A provider wrapper** that any interface can put around any provider.

## Decision
Option 3: `RetryingProvider`. Adapters only classify errors (`ProviderError.retryable`,
`retry_after`). The wrapper retries up to 4 times with exponential backoff (0.5 s doubling,
capped at 20 s, ±25% jitter), uses a server's `Retry-After` when given, stops when the total
wait would exceed 90 s, and then tries an optional fallback provider once. A stream is retried
only if it fails before yielding anything.

## Consequences
- The loop and the adapters stay unchanged; tests inject `sleep` and a seeded random generator.
- Giving up on an unreachable local server takes longer than the backoff alone: on Windows each
  refused connection to `localhost` took about 4 s (2 s per address, IPv6 then IPv4), so five
  attempts took 28.5 s of which 8 s were deliberate waits.
- A failure after text has been streamed ends the turn with an error rather than a hidden restart.
