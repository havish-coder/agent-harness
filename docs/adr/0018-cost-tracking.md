# 0018. Track cost from token counts with a small, dated price table

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Cloud models are paid per token, with different prices for input, output, and prompt-cache
writes and reads. Users should see what a task costs as they work. Prices differ between
vendors, change over time, and depend on plans and discounts; a wrong price shown with
confidence is worse than none.

## Options
1. **No cost display**: honest, but users are blind to spending.
2. **A large built-in price list for every vendor**: convenient; goes stale silently.
3. **A small built-in list we can verify, dated, plus user-supplied prices.**

## Decision
Option 3. Built in: Anthropic's published prices (fetched 2026-10-06) and zero for local
providers. Everything else comes from the `prices` setting. A model with no known price shows
"price unknown", never "free". Cost = uncached input + cache writes + cache reads + output, each
at its own rate. Usage is tracked per model, because a fallback model may answer some calls.

## Consequences
- Accurate for the providers we can verify; the user stays in charge of the rest.
- The table must be updated (and re-dated) when Anthropic's prices change.
- Tokenizers differ between models, so estimating one model's cost from another's token counts
  is only approximate.
