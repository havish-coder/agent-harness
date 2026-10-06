# 0006. Read files in numbered, bounded pages

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
`read_file` returned a whole file. With an 8,192-token context, one 108 KB log file overflowed
the window, and once results were capped at 8,000 characters the model **invented** a line
from the part that was cut: asked for line 1500, it answered with a plausible but wrong value,
twice. A cap needs a way past it.

## Options
1. **Whole file, capped**: simple; content beyond the cap is invisible and gets guessed.
2. **Pages with offset/limit, plain text**: the model can ask for any part, but can't easily
   say *which* line it is looking at.
3. **Pages with offset/limit and line numbers** (`cat -n` style), plus a header saying which
   lines were returned and how to get the next page.

## Decision
Option 3. Defaults: 300 lines, about 7,000 characters, 500 characters per line. `offset` is
1-based; `0` is accepted as `1` and negative values count from the end, because live tests
showed the model sending `offset=0` and struggling to reach the last line.

## Consequences
- In live tests, line lookups went from 0/2 correct to 6/6, including "the last line".
- Line numbers cost tokens on every read: the average input of our 12-question check rose
  from 974 to 1,331 tokens.
- Edit tools must tell the model that line numbers are not part of the file (models copy them).
