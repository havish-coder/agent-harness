# The context window

A model reads a fixed amount of text at once, its **context window**. With a local Ollama model the harness picks the
size that fits your GPU (8,192 tokens for `qwen3:4b-instruct` on a 4 GB GPU, 65,536 on a 12 GB one: [a bigger window](#a-bigger-window)),
and `/window` changes it while you work; Claude models read 200,000. A token is
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

A bigger window costs memory and speed: see [a bigger window](#a-bigger-window) below.

## A bigger window
The system prompt and the tool definitions take 2,000 to 3,500 tokens before you type anything, and a quarter of the window
is kept for the reply, so an 8,192-token window fills after a few files. A bigger one holds more, but every token of it costs
memory in the model server whether the conversation uses it yet or not, and what doesn't fit on the GPU runs on the CPU,
much more slowly. So the harness sizes it for your computer, and you can change it at any time.

### Auto: the size that fits your GPU
`context_window` is `auto` unless you set a number. At start the harness works out, for a local Ollama model:

1. **What the model needs**: Ollama's `/api/show` gives its layers, its KV heads, the size of each and its own longest window;
   `/api/tags` the size of its weights. For each token in the window the model keeps keys and values for every layer (the
   *KV cache*): `2 × layers × KV heads × head size × bytes per number`. For `qwen3:4b-instruct` that is
   2 × 36 × 8 × 128 × 2 = 147,456 bytes a token, 1.2 GB per 8K.
2. **What the GPU has**: the free memory `nvidia-smi` reports, plus what Ollama's loaded models hold (Ollama unloads them to
   make room). On a Mac with Apple silicon, two thirds of the memory (what the GPU may use of it).
3. **The size**: the largest multiple of 8,192 where the weights, the cache and about 0.4 GB of working buffers fit, so the whole
   model stays on the GPU (that is what keeps answers fast). Never less than 8,192, never more than the model's own limit or
   131,072 (set a number to go higher).

What it picks for `qwen3:4b-instruct` by the GPU's memory (if all of it is free; a desktop and other programs use some):

| GPU memory | auto | auto with an 8-bit cache ([below](#make-room-for-it-in-memory-ollama)) |
|---|---|---|
| 4 GB | 8,192 | 16,384 |
| 6 GB | 16,384 | 40,960 |
| 8 GB | 32,768 | 73,728 |
| 12 GB | 65,536 | 131,072 |
| 16 GB | 90,112 | 131,072 |
| 24 GB | 131,072 | 131,072 |

The 4 GB row is checked against the laptop the measurements below were made on (an RTX 3050): weights 2.5 GB + cache 1.2 GB +
buffers 0.4 GB is the 4.1 GB `ollama ps` reported at 8K. A bigger window doesn't fit beside the model there, so auto keeps
8,192 and says why:

```text
context window: 8,192 tokens (auto: 8,192: a bigger window wouldn't fit beside qwen3:4b-instruct (2.3 GB) on your 4.0 GB GPU,
so part of the model runs on the CPU) · /window changes it
```

When it can't measure, auto gives 8,192: no NVIDIA GPU or Apple silicon found, an Ollama server on another computer (its GPU
can't be seen from here), LM Studio or another OpenAI-compatible server (they don't say how big the model is), a model Ollama
doesn't describe. A cloud model's window is known from its name (Claude 200,000: [window sizes](#window-sizes)). The size and
the reason are shown at start, by `/context`, `/window` and the web page's Settings.

### Change it while you work: `/window`
```text
> /window
context window: 8,192 tokens (auto: 8,192: a bigger window wouldn't fit ...)
qwen3:4b-instruct: up to 262,144 tokens; 2.3 GB of weights + 1.1 GB of cache per 8K (half that with OLLAMA_KV_CACHE_TYPE=q8_0)
/window 16384 sets a size, /window auto sizes it for your GPU (the context guide has the trade-offs)
> /window 16k
context window: 16,384 tokens (set to 16,384). Ollama reloads the model once at the new size.
```

`/window N` (or `16k`) sets a size of at least 4,096, `/window auto` measures again. The conversation carries on: the next
model call asks Ollama for the new size (it reloads the model, a few seconds), and the harness plans with it from then on (the
reply's share, the system prompt's share, [tool search](tool-search.md)). Making it smaller than the conversation already is
works too: old results are cleared and the conversation summarised to fit, as when it fills ([below](#when-the-window-fills-clearing-old-results)).
In the [web page](web-ui.md) the same is in Settings, under Context window: a size and **Apply**, or **Auto: fit my GPU**.
`/window` lasts for the session; to keep a size, set it:

### Set it for good
Any of these, the most specific winning:

| for | how |
|---|---|
| one run | `harness --context-window 16384` (or `auto`) |
| every run | `"context_window": 16384` in `~/.harness/settings.json` (Windows: `C:\Users\<you>\.harness\settings.json`) |
| one project | the same line in `<project>/.harness/settings.json` or `settings.local.json` |
| one terminal | the environment variable `HARNESS_CONTEXT_WINDOW=16384` |

A number is always used as it is, even if it doesn't fit your GPU (the model then runs partly on the CPU: the tables below
show what that costs). Use a multiple of 1,024; the smallest the harness accepts is 4,096. With Ollama the harness asks for
exactly that many tokens (Ollama's `num_ctx`), so the server and the harness agree. With a cloud model the setting is only
needed for a model the harness doesn't know.

Check it took: `/context` says `of 16,384 tokens`, the status line says `/16.4k`, and `harness --show-config` shows
where the value came from.

### Make room for it in memory (Ollama)
Every token in the window needs memory in the model server, whether the conversation uses it yet or not. Measured with
`qwen3:4b-instruct` on a laptop with a 4 GB GPU (RTX 3050) and 16 GB of RAM:

| window | memory | on the GPU | writing speed, half full | writing speed, nearly full |
|---|---|---|---|---|
| 8,192 | 4.1 GB | 55% | 6.0 tokens/s | |
| 16,384 | 5.4 GB | 42% | 4.6 tokens/s | 2.0 tokens/s |
| 32,768 | 8.0 GB | 27% | 4.0 tokens/s | 0.7 tokens/s |

What doesn't fit on the GPU runs on the CPU, so a bigger window works on a small GPU but answers more slowly, and much
more slowly once the window is actually full: a 100-token answer took two and a half minutes at 32K.

Two options of the Ollama server shrink that memory: **flash attention**, a faster way to compute attention, and an
**8-bit KV cache**, which stores what the model has read in 8 bits instead of 16. On the same machine:

| window | memory | on the GPU | writing speed, half full | writing speed, nearly full |
|---|---|---|---|---|
| 8,192 | 3.6 GB | 64% | 10.3 tokens/s | |
| **16,384** | **4.3 GB** | **54%** | **8.4 tokens/s** | **3.8 tokens/s** |
| 32,768 | 5.7 GB | 39% | 7.0 tokens/s | 1.7 tokens/s |

With them, a 16K window is faster than the default 8K window without them. Each 8K of window costs about 0.7 GB
instead of 1.3 GB. The 8-bit cache is generally reported to change answers very little; `q4_0` instead of `q8_0` halves
the memory again with a larger loss (not measured here).

To turn them on, set two environment variables for the Ollama server and restart it:

- **Windows**: run `setx OLLAMA_FLASH_ATTENTION 1` and `setx OLLAMA_KV_CACHE_TYPE q8_0`, then quit Ollama from the
  system tray and start it again.
- **macOS**: run `launchctl setenv OLLAMA_FLASH_ATTENTION 1` and `launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0`, then
  quit and reopen the Ollama app.
- **Linux** (systemd): `sudo systemctl edit ollama.service`, add the lines below, then `sudo systemctl restart ollama`:
  ```ini
  [Service]
  Environment="OLLAMA_FLASH_ATTENTION=1"
  Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
  ```

Check: with a model loaded, `ollama ps` shows a smaller SIZE than before (here 3.6 GB instead of 4.1 GB at 8K).

**Auto knows about them** when they are set where the harness can see them too (`setx` and `launchctl setenv` set them for
every program you start afterwards): with `OLLAMA_FLASH_ATTENTION=1`, the cache counts the bytes `OLLAMA_KV_CACHE_TYPE` says
(1 for `q8_0`, half for `q4_0`), so on a 4 GB GPU auto picks 16,384 instead of 8,192. Without flash attention Ollama ignores
the cache type, and so does auto. Then check with `ollama ps` that it says `100% GPU`: that is what keeps answers fast. A model
has its own limit too (`ollama show <model>` lists the context length; 262,144 for `qwen3:4b-instruct`).

The harness prints sizes in GiB (2<sup>30</sup> bytes, as GPUs are sold), `ollama ps` in decimal GB: the same 1.21 billion bytes
of cache per 8K are "1.1 GB" in one and "1.2 GB" in the other.

### Or need less of it
- **Fewer tools.** Each tool is described in every request. Turning off what you don't use saves its share:
  `"web_fetch": false`, `"subagents": false`, `"skills": false`, `"todo": false`, `"background_tasks": false`,
  `"auto_memory": "off"`. With all of these off, the start-up cost went from about 3,400 tokens to 1,800.
- **Look at the system prompt.** `/prompt` lists its sections and what each costs. A long [progress journal](journal.md)
  or `HARNESS.md` is read into every request.
- **Read less at once.** `grep` before `read_file`, ask for the lines you need, `/reset` between tasks. Old results are
  cleared, then the conversation summarised, as it fills (below).
- **A cloud model** for a job that needs a whole codebase in view: Claude reads 200,000 tokens
  ([choosing a model](models.md)).

### What else changes with the size
The harness plans everything from the window: a quarter is kept for the reply (at most `max_output_tokens`, 4,096),
the system prompt may use a quarter (so a bigger window shows more of the workspace listing), [tool search](tool-search.md)
stops holding tools back once their definitions are under 15% of it, and clearing and summarising start later.

## Window sizes
For cloud models the harness knows the window by model name (Claude 200K, GPT-4o 128K, Gemini 1M, ...);
a model it doesn't know is planned as 32,000 tokens, so it errs on the side of stopping early. A local model's window is
what the harness asks the server for: auto's size ([above](#auto-the-size-that-fits-your-gpu)) or yours. A number in the
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
  (its output) and `web_fetch`. Edits and writes are never cleared. The **newest two** results big enough to matter are kept whole
  (`microcompact_keep`), and if the conversation is still nearly full the harness keeps only the newest one. And only results
  the agent has **used**: since it read them, it wrote something or made a call that changes things. What it has only read, and
  gone on reading, exists nowhere else, so it is left for the [summary](#summarising-the-conversation-compact); the
  agent clears those too only when nothing else made room.
- **How far.** Oldest first, until the conversation is at half of what it may use, so it doesn't start again on the very
  next call. A result too small to be worth a note is left alone.
- **What a note says.** The call, its size and its length, never the result's own words: a cleared file or web page may
  have contained text written by someone else, and a note sits outside the `<untrusted>` fence.
- **Seeing it.** `/context` adds a line (`4 old tool results cleared to make room (~8,100 tokens)`), and the
  [audit log](audit-and-limits.md) records which tools and how many tokens.
- **Turning it off.** `"microcompact": false` in your settings. The agent then stops with `context_full` as before.

**What you lose.** Anything the agent saw only in a cleared result and did not use or write down. A task that *uses*
each result as it goes (read a file, change it, run the tests) loses nothing. A task that *collects* from many sources
for an answer at the end is protected by the rule above (results the agent has only read are summarised, not cleared), but if
you turn summaries off (`"auto_compact": false`) the agent clears them anyway rather than stop, and what it collected can be lost:
the system prompt asks the model to write down what it needs, but small models do not always do it. When clearing isn't enough, or the task needs what was in the cleared results,
[summarising](#summarising-the-conversation-compact) is the next step.

## Summarising the conversation: `/compact`
When the conversation **no longer fits** the window (and clearing old results has not made enough room), the harness asks the
model, once and without tools, to **summarise the older part of the conversation**, and carries on from the summary:

```text
  ↺ the window is nearly full: summarising 14 older messages ...
  ↺ summarised 14 messages (~6,200 -> ~2,100 tokens)
```

What the conversation looks like afterwards: your system prompt, **one message holding the summary**, and the most recent
messages exactly as they were. The summary has three headings: *Request*, *Done* (files read or changed, commands run, what was
found, with the exact names and values that matter) and *Open* (what is left, what failed). Your **current request is kept word for
word** in that message, because a summary can drop a requirement.

- **Kept as they were.** About the newest 30% of the window's budget, and always the last exchange (the newest tool call and its
  result), because the model is about to act on it. The cut never falls between a call and its results.
- **`/compact`** does it now, whenever you like. `/compact the discount rules` tells the summary what to pay attention to.
  `/context` says how many times it has happened.
- **`"auto_compact": false`** in your settings turns the automatic summary off; `/compact` still works. The agent then stops with
  `context_full` when the window is full.
- **What it costs.** One model call (counted in `/cost` and the limits), and the next request is read from scratch by the
  model server because the start of the conversation changed.
- **It can be wrong.** A summary is the model's own account, written by a small model from shortened results (each result is cut to
  a few hundred characters for the summary request). Check what it says if the task depends on a detail. `/export` writes the
  whole chat, summarised messages included, and leaves the summary text out.
- **Untrusted content stays untrusted.** If this chat has read a web page, or a file from a folder you haven't trusted, the
  summary is wrapped in `<untrusted>` tags like the content it came from, so a page's instructions don't become instructions of
  the harness's own by being summarised. (`/trust` and the [untrusted content](untrusted-content.md) page explain the rule.)
- **If the summary fails** (the model is unreachable, or writes nothing) the conversation is left as it was and the agent
  carries on, or stops if the window is full.
