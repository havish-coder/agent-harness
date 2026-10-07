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

## The system prompt
The system prompt is the standing instruction at the start of every request. The harness builds it from named
sections, **most stable first**:

| Section | Holds | Changes |
|---|---|---|
| role | what the agent is, how to use its tools | never |
| untrusted content | the rule for text wrapped in `<untrusted>` tags ([details](untrusted-content.md)) | with the `fence_untrusted` setting |
| clearing rule | what a `[cleared to save space ...]` note means (only while `microcompact` is on) | with the `microcompact` setting |
| output style | the style chosen with `/style` (none for `default`) | with `/style` |
| environment | today's date, the system, the shell `run_shell` uses, the git branch and how many files changed | per session |
| workspace files | a listing of the folder, taken at session start | per session |

`/prompt` lists them with their cost:

```text
system prompt: ~273 tokens of a 2,048 budget (8,192-token window, 25% allowed)
  role                   73  changes: never
  untrusted content      65  changes: with a setting
  clearing rule          42  changes: with a setting
  environment            50  changes: per session
  workspace files        43  changes: per session
```

`/prompt full` prints exactly what the model reads.

**Why this order.** A model server keeps the computed state of the start of the last prompt and reuses it up to
the first character that differs. The harness never changes the system prompt between turns, so each turn only
costs the new messages: on `qwen3:4b-instruct` about 250 ms, against 1,100 to 1,300 ms when the system prompt
differs from the last request. Changing it mid-session (`/style`) is allowed and costs that second once.

**The budget.** The system prompt may use a quarter of the window (never less than 600 tokens). On a small window
or in a folder with thousands of files the harness first **shrinks the file listing** to fit, then drops optional
sections, the most volatile first. `/prompt` marks them, for example `workspace files  310  [shrunk from 1,240]`.
The role and the untrusted-content rule are never dropped. If a listing is cut, ask the agent to use `glob` or
`list_dir` to see the rest, or raise `context_window`.

## When the window fills: clearing old results
Most of a long conversation is tool results: whole files, search hits, test output. A result matters while
the agent works on it and rarely afterwards, and for a read or a search the agent can simply ask again. So when the
conversation passes 70% of what the window allows, the harness **replaces the oldest results with short notes**:

```text
[cleared to save space: read_file(path='src/cart.py'), about 2,698 tokens, 133 lines. Call the tool again if you still need it.]
```

and the line `↺ the window is filling: cleared 3 old results (~7,900 tokens)` appears in the terminal. No model call is
involved, nothing is summarised, and the messages keep their place in the history; only the text of the result is gone.

- **Which results.** Only those of tools that can be asked again: `read_file`, `grep`, `glob`, `list_dir`, `run_shell`
  (its output) and `web_fetch`. Edits and writes are never cleared. The **newest two** results are kept whole
  (`microcompact_keep`), and if the conversation still doesn't fit the harness keeps only the newest one.
- **How far.** Oldest first, until the conversation is at half of what it may use, so it doesn't start again on the very
  next call. A result too small to be worth a note is left alone.
- **What a note says.** The call, its size and its length, never the result's own words: a cleared file or web page may
  have contained text written by someone else, and a note sits outside the `<untrusted>` fence.
- **Seeing it.** `/context` adds a line (`4 old tool results cleared to make room (~8,100 tokens)`), and the
  [audit log](audit-and-limits.md) records which tools and how many tokens.
- **Turning it off.** `"microcompact": false` in your settings. The agent then stops with `context_full` as before.

**What you lose.** Anything the agent saw only in a cleared result and did not use or write down. A task that *uses*
each result as it goes (read a file, change it, run the tests) loses nothing. A task that *collects* from many sources
for an answer at the end can lose what it collected; the system prompt asks the model to write down what it needs from
a result before moving on, but small models do not always do it. If a long collecting task matters, split it into steps,
or ask the agent to write its findings to a file as it goes. To go further than clearing can, `/reset` starts a fresh chat;
summarising a long conversation (compaction) is planned for the same release.
