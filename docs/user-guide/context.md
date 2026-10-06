# The context window

A model reads a fixed amount of text at once, its **context window**: `qwen3:4b-instruct` on Ollama
reads 8,192 tokens by default (the `context_window` setting), Claude models 200,000. A token is
a piece of a word: about 3 to 4 characters of English, but as little as 2.4 characters in test output and
tables, and **each digit counts as one and a half tokens**.

Everything the model sees in a request must fit: the system prompt, the **tool definitions** (they are sent
with every request: about 1,500 tokens for the built-in tools, a fifth of an 8K window), your messages,
its own replies, and every tool result.

## `/context`
```text
context: ~2,527 of 8,192 tokens (31%); 600 are kept free for the reply, so the conversation may use 7,592
  system prompt          184    7%
  tool definitions     1,467   61%
  your messages           32    1%
  assistant              146    6%
  tool results           542   22%  (read_file 542)
the model server last reported reading 2,435 tokens (our estimate is calibrated by 1.07x)
plenty of room
```

The status line under the prompt shows the same estimate (`context ~2.5k/8.2k (31%)`), and the line after
each answer ends with `context ~31%`. The numbers are **estimates** made by the harness: it counts characters
by kind, and corrects itself against what the model server reports. They are usually within about 10%.

## When it gets full
Model servers differ in what they do with a prompt that is too long, and the usual answer is the worst
one: **they cut it silently**. In our test, Ollama with an 8,192-token window was sent a 9,000-word
conversation: it read the end, forgot the start (a code word given in the first message), and *reported*
that it had read 45 tokens. So the harness doesn't send what won't fit. When the conversation would
use the whole window (minus a quarter kept for the reply), the agent stops and says so:

```text
(stopped: the conversation is about 8,310 tokens and the model's window leaves room for 7,592.
/context shows where they go; /reset starts a new chat)
```

What fills a window fastest: whole-file reads and long command output (the results of `run_shell` are
capped at about 7,000 characters, a read at 300 lines). To keep room, ask for the part of a file you
need, use `grep` before `read_file`, and start a new chat (`/reset`) for a new task.

A bigger window costs memory and speed: for Ollama set `"context_window": 16384` in your settings and
check that the model still fits your GPU (see [choosing a model](models.md)).

## Window sizes
For cloud models the harness knows the window by model name (Claude 200K, GPT-4o 128K, Gemini 1M, ...);
a model it doesn't know is planned as 32,000 tokens, so it errs on the side of stopping early. The
`context_window` setting overrides all of it.
