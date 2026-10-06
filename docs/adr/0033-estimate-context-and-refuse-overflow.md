# 0033. Estimate the conversation's size ourselves, and refuse to send what won't fit

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
A model reads a fixed window. Until now the harness trusted the server's report of the last request
(`prompt_eval_count`) for the status line, and sent whatever the conversation had grown to. Two measurements
on `qwen3:4b-instruct` with Ollama (`num_ctx` 8192) show why that isn't enough:

- **Overflow is silent and the report lies.** A first message containing a code word, then 14,000 words of
  filler: below about 7,600 tokens the model found the word; at 9,000 words Ollama cut the prompt, the
  model "didn't remember any code word", and the reported prompt size was **45 tokens**. The server's own
  number can't tell you the conversation no longer fits, because it describes what was left after the cut.
- **The usual estimate is wrong where it matters.** `characters / 4` was 6% low on average on 55 samples of
  this project's text and tool output, and **63% low** on digit-heavy output: pytest lines are 2.4
  characters per token, tables 2.9, numbered file listings 3.4, because digits are split one by one.
  The cases where the estimate is most wrong are the large tool results that fill the window.

## Options
1. **Trust the server's count.** Exact when it works, blind to the overflow above, and only available after the call.
2. **Use the model's tokenizer** (install a library, or call a tokenize endpoint). Exact, but a dependency per
   model family, absent for most cloud APIs, and a network call per check.
3. **`characters / 4`.** Free and wrong in the dangerous direction.
4. **Estimate from character kinds, fitted to a real tokenizer, and calibrate against the server's reports when
   they are believable.**

## Decision
Option 4 (`harness/context/tokens.py`).

- `estimate_tokens(text)` = letters × 0.2 + digits × 1.45 + punctuation × 0.5 + white space × 0.2 (least squares on
  the samples; mean error under 3%, worst case about -14% / +19%), plus a small per-message and per-call overhead.
  Tool definitions are counted once per request.
- `Calibrator` keeps a smoothed ratio of reported to estimated tokens, clamped to 0.7-1.6. A report **below 60% of
  the estimate is ignored**: that is the signature of a server cut, not a measurement.
- `ContextBudget` compares `estimate × calibration × 1.1` with the window minus a reserve for the reply (a quarter of
  the window at most), and names a level: `ok`, `warn` (70%), `critical` (90%), `full`.
- The agent checks before **every model call**. At `full` it **stops** (`stop_reason: context_full`) with a message
  that names the numbers and says what to do, instead of letting the server cut the conversation silently.
- The window comes from the `context_window` setting for Ollama and for any explicit setting, from a table of model-name
  prefixes for cloud models, and is 32,000 for an unknown cloud model (cautious).
- `/context` shows where the tokens go (system prompt, tool definitions, messages, results by tool); the status line shows
  the estimate marked with `~`.

## Consequences
- The overflow measured above can't happen unnoticed: the user is told, with numbers, before the model is called.
- Stopping is blunt: a conversation that reaches the limit is stuck until `/reset`. That is accepted for this lesson and is
  the problem the next lessons solve (shrinking old results, summarising old turns); the estimate and levels built here
  are what those lessons trigger on.
- The estimate is fitted to one tokenizer (qwen3's). Other tokenizers differ by tens of percent on some text; the
  calibrator absorbs a consistent offset, and the 1.1 margin covers the rest. A cloud provider that reports exact input
  tokens makes the calibration accurate within a call or two.
- Tool definitions are 1,467 tokens, 61% of a small conversation: the schemas are the biggest fixed cost, which is what
  later lessons on deferring tool definitions address.
- The fit constants are data, not law: re-fit them (the procedure is in the lesson) when changing the default model.
