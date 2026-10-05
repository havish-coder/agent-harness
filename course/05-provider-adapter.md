# Lesson 05 · The Provider Adapter

> **Module 1: The Agent Loop** · All of Ollama's details (its JSON shape, its errors, its
> quirks) get locked into one file behind a one-method interface. After this lesson, the rest
> of the harness can talk to "a model" without knowing which one.

## Learning objectives
By the end of this lesson you can:
1. Explain the adapter pattern and why `Provider` is a `Protocol` rather than a base class.
2. Trace a call through `to_ollama()` → HTTP → `from_ollama()` and say what each step does.
3. List the model and vendor quirks the adapter absorbs, and why the edge is the right place.
4. Explain why every failure becomes a single `ProviderError`.
5. Estimate the token and memory cost of tools and of `num_ctx`.

---

## 1. Learn

### 1.1 The adapter pattern

An adapter converts one interface into another, like a travel plug adapter. Ours sits between
the harness's types (Lesson 04) and Ollama's HTTP API:

```
   harness core                    OllamaProvider                          Ollama server
 ┌──────────────┐  list[Message]  ┌──────────────────┐   JSON over HTTP   ┌─────────────┐
 │ agent loop   │ ──────────────► │ to_ollama()      │ ─────────────────► │ /api/chat   │
 │              │                 │ chat(): HTTP,    │                    │             │
 │              │ ◄────────────── │  errors          │ ◄───────────────── │             │
 └──────────────┘      Reply      │ from_ollama()    │                    └─────────────┘
                                  └──────────────────┘
```

Everything to the left of the adapter only sees `Message`, `ToolCall`, `Reply` and
`ProviderError`. Everything Ollama-specific lives inside `harness/providers/ollama.py`.

### 1.2 The interface: one method, as a `Protocol`

```python
class Provider(Protocol):
    model: str
    def chat(self, messages: list[Message], tools: list[dict]) -> Reply: ...
```

There are two ways to define an interface in Python:

| | `ABC` (abstract base class) | `Protocol` (structural typing) |
|---|---|---|
| How a class qualifies | must **inherit**: `class OllamaProvider(Provider)` | just **has the right methods**, no inheritance needed |
| Checked by | Python at runtime (can't instantiate if methods are missing) | type checkers / editors |
| Feels like | a formal contract | "if it quacks like a duck..." |

We use `Protocol` because providers come from many places: our Ollama adapter, an OpenAI
adapter (Lesson 14), and **test fakes** (Lesson 13) that just return scripted replies. None of
them should need to import and inherit from a base class to count as a provider.

### 1.3 Neutral tool schemas

The agent hands the provider tools in a neutral shape:
```json
{"name": "read_file", "description": "...", "parameters": {<JSON Schema>}}
```
Each provider wraps it in its own format. Ollama and OpenAI want
`{"type": "function", "function": {...}}`, and Anthropic wants `{"name", "description",
"input_schema"}`. One line in the adapter does this, and the rest of the harness never
knows.

### 1.4 Outgoing: `to_ollama()`

| Our `Message` | Ollama JSON |
|---|---|
| `role`, `content` | copied as-is |
| `tool_calls: [ToolCall(id, name, arguments)]` | `tool_calls: [{"id", "function": {"name", "arguments"}}]` |
| `tool_name` (on tool messages) | `tool_name`, which Ollama uses to match results to calls |
| `tool_call_id` | not sent; Ollama doesn't use it. Other adapters will. |

### 1.5 Incoming: `from_ollama()`, and cleaning up at the edge

A useful design rule is *"be liberal in what you accept, strict in what you produce"*. The
adapter accepts every messy thing a model or server might send and produces clean, predictable
`Reply` objects:

| Mess coming in | What the adapter does |
|---|---|
| Thinking leaks into `content`, ending in `</think>` (Lesson 01's bug) | strips everything up to `</think>` |
| `arguments` arrives as a JSON **string** (some models do this) | parses it with `json.loads` |
| ...and that string is **invalid** JSON | keeps it as `{"_unparsed": "<text>"}`. The tool then fails with a clear error the model can read, instead of the whole run crashing here. |
| A tool call with **no `id`** | generates one: `uuid.uuid4().hex[:12]` |
| `done_reason: "length"` | `stop_reason = "max_tokens"` |
| `done_reason: "stop"` with tool calls present | `stop_reason = "tool_calls"` |
| missing token counts | default to `0` |

Why fix things here? Because otherwise **every** consumer of a reply has to remember every
quirk. Clean once, at the edge, and the core can trust the data.

### 1.6 One exception type: `ProviderError`

Many things can go wrong under `chat()`:

```
httpx.ConnectError ───────┐
httpx.TimeoutException ───┼──►  ProviderError("cannot connect to Ollama at ... Is it running?")
HTTP 404 / 400 / 500 ─────┘     ProviderError("Ollama returned HTTP 404: {"error":"model 'x' not found"}")
```

The CLI (and later the web server) needs **one** `except ProviderError` clause, whatever the
provider and whichever HTTP library is underneath. The messages are written for humans.

`raise ProviderError(...) from None` hides the original `httpx` traceback. Without
`from None`, Python prints both errors ("During handling of the above exception, another
exception occurred"), which is noisy for a user and adds nothing.

### 1.7 One HTTP client, reused

```python
self.http = httpx.Client(base_url=url, timeout=httpx.Timeout(timeout, connect=10))
```
- **Connection reuse.** A `Client` keeps the TCP connection open between requests
  (keep-alive). An agent makes many calls per task, so skipping the reconnect each time adds up.
- **`base_url`.** Calls become `self.http.post("/api/chat", ...)`.
- **Timeouts** as in Lesson 02: fail fast if the server is down (10 s to connect), but allow
  slow generation (300 s to read).

### 1.8 What tools cost

Measured on your machine:

| Request | Input tokens |
|---|---:|
| "Say hi in 3 words.", no tools | 15 |
| same, **with one** small tool schema | 153 |

About **140 tokens per tool**, sent on **every** call. An agent with 15 tools taking 10 steps
spends about 21,000 input tokens on tool descriptions alone. Rules of thumb: keep descriptions
tight, and only offer the tools a task needs.

### 1.9 Why `num_ctx=8192`, and what it costs

Lesson 01 showed Ollama defaulted to a 4,096-token context. One system prompt, a few tool
schemas and one medium file fill that quickly, and overflow is **silent** (Lesson 01,
Experiment 5). So the adapter asks for 8,192.

The cost is memory for the **KV cache**: for each context token, every layer stores a *key*
and a *value* vector. From `ollama show -v qwen3:4b-instruct`: 36 layers, 8 KV heads, 128
dimensions each, 2 bytes per number:

```
2 (key + value) × 36 layers × 8 heads × 128 dims × 2 bytes = 147,456 bytes ≈ 144 KB per token
4,096 extra tokens × 144 KB ≈ 0.6 GB
```

And measured with `ollama ps`:

| `num_ctx` | Loaded size | CPU / GPU split |
|---:|---:|---|
| 4,096 | 3.5 GB | 36% / 64% |
| 8,192 | 4.1 GB (+0.6 GB, as predicted) | 45% / 55% |

More context means more of the model runs on the slower CPU. It's a trade-off: we accept a
bit of speed loss to avoid silent truncation. Module 5 will manage the context properly.

---

## 2. Build

### `harness/providers/base.py`
The `Provider` protocol (section 1.2), `ProviderError`, and a docstring saying what shape tool
schemas have. About 25 lines, no logic.

### `harness/providers/ollama.py`, walkthrough

**`__init__`**: stores the model name, builds `options` (`num_ctx`, plus `temperature` only
if you set one, otherwise the model's recommended default applies) and creates the reusable
HTTP client.

**`chat()`**:
```python
body = {"model": self.model, "messages": [to_ollama(m) for m in messages],
        "stream": False, "options": self.options}
if tools:
    body["tools"] = [{"type": "function", "function": t} for t in tools]   # neutral → Ollama
```
Then the request, inside `try`/`except`: `ConnectError` and `TimeoutException` become
`ProviderError`, then `r.is_error` (4xx/5xx) does too, and finally `from_ollama(r.json())`.
Streaming is off for now. Lesson 12 adds it.

**`to_ollama(m)`**: section 1.4's table, in 10 lines.

**`from_ollama(data)`**: section 1.5's table, in order: strip leaked thinking, then build
`ToolCall`s (parse string arguments, generate missing IDs), then work out `stop_reason`, then
`Usage`.

Note that `to_ollama` and `from_ollama` are **plain functions**, not methods. They don't need
any provider state, so you can test them alone by feeding them fake dicts, with no
server needed. Experiment 3 does exactly that.

---

## 3. Understand: experiments

```bash
.venv\Scripts\python
```
```python
from harness.messages import Message
from harness.providers.ollama import OllamaProvider, from_ollama
from harness.providers.base import ProviderError
p = OllamaProvider()
```

### Experiment 1: A plain call
```python
p.chat([Message.user("Say hi in 3 words.")], [])
```
You get a `Reply` with `stop_reason='end'` and `usage`. No Ollama JSON anywhere.

### Experiment 2: A tool call, translated
```python
tools = [{"name": "read_file", "description": "Read a text file from the workspace",
          "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}]
r = p.chat([Message.user("What is in notes.txt?")], tools)
r.stop_reason, r.message.tool_calls, r.usage
```
Expect `'tool_calls'`, a `ToolCall(... name='read_file', arguments={'path': 'notes.txt'})`, and
about 150 input tokens. Compare with the 15 tokens of Experiment 1.

### Experiment 3: Feed the adapter messy data (no server needed)
```python
from_ollama({"message": {"content": "Hmm, let me think...</think>\n\nsetup works"}, "done_reason": "stop"})
from_ollama({"message": {"content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": "{\"path\": \"notes.txt\"}"}}]}})
from_ollama({"message": {"content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": "{\"path\": notes.txt"}}]}})
from_ollama({"message": {"content": "Once upon a"}, "done_reason": "length"})
```
Predict each result before you run it: leaked thinking stripped; string arguments parsed and an
`id` generated; invalid JSON kept as `_unparsed`; `stop_reason='max_tokens'`.

### Experiment 4: Errors become `ProviderError`
```python
try:
    OllamaProvider(model="nope:1b").chat([Message.user("hi")], [])
except ProviderError as e:
    print("model error:", e)

try:
    OllamaProvider(url="http://localhost:9999").chat([Message.user("hi")], [])
except ProviderError as e:
    print("connection error:", e)
```

### Experiment 5: See the memory cost of context
Run a call, then in another terminal:
```bash
ollama ps
```
Then try `OllamaProvider(num_ctx=16384).chat(...)` and run `ollama ps` again. Watch the size
and the CPU/GPU split change.

---

## 4. Review

### Quiz
1. Why is `Provider` a `Protocol` and not an abstract base class?
2. Name three quirks `from_ollama()` absorbs, and why they're handled there rather than in the loop.
3. Why turn *invalid* JSON arguments into `{"_unparsed": ...}` instead of raising an error?
4. What does `raise ... from None` change?
5. Going from `num_ctx` 4,096 to 8,192 added about 0.6 GB. Using 144 KB per token, how much
   would 32,768 tokens of KV cache take?

### Exercise 1: A provider in 6 lines
Write `PongProvider`: a class with a `model` attribute and a `chat()` that always returns a
`Reply` whose message says `"pong"`. No HTTP. Then call its `chat()` with any messages. Does
it satisfy `Provider`? (You've just written your first test fake. Lesson 13 builds on this.)

### Exercise 2: Keep the model loaded
Ollama unloads a model after 5 idle minutes, and reloading costs seconds. Ollama's chat API
accepts a top-level `"keep_alive": "30m"` field. Add a `keep_alive` parameter to
`OllamaProvider.__init__` and put it in the request body.

### Checkpoint
Without looking, list what `chat()` does in order, from building the body to returning a `Reply`.

---

### Answers

<details><summary>Quiz answers</summary>

1. Any class with the right `chat()` method counts, whether it's a real adapter or a 6-line
   test fake, with no need to inherit from or import a base class.
2. Leaked `</think>` reasoning, string or invalid JSON arguments, missing IDs, `length` →
   `max_tokens`, `stop` with tool calls → `tool_calls`. Handling them at the edge means one
   fix serves every consumer, and the core can trust `Reply` objects.
3. Raising would crash the whole agent run over one bad call. Passing it through lets the tool
   fail with an error message the model can read, so it can retry with valid JSON.
4. It suppresses the chained "during handling of the above exception..." traceback, so the user
   sees one clear error.
5. 32,768 × 144 KB ≈ **4.5 GB**, more than your whole GPU, just for the KV cache.
</details>

<details><summary>Exercise answers</summary>

**1.**
```python
from harness.messages import Message, Reply, Usage

class PongProvider:
    model = "pong"
    def chat(self, messages, tools):
        return Reply(Message("assistant", "pong"), "end", Usage())

PongProvider().chat([Message.user("ping")], [])
```
Yes: it has `model` and a matching `chat()`, so it satisfies the `Provider` protocol with no inheritance.

**2.**
```python
def __init__(self, ..., keep_alive="30m"):
    ...
    self.keep_alive = keep_alive

# in chat():
body["keep_alive"] = self.keep_alive
```
</details>

### Glossary
- **Adapter pattern**: converting one interface into another so incompatible parts can work together.
- **Protocol / structural typing**: a type is defined by the methods it has, not by what it inherits.
- **KV cache**: the stored key and value vectors for each context token, which makes long contexts memory-hungry.
- **Keep-alive (HTTP)**: reusing one TCP connection for several requests.
- **Exception chaining**: Python linking a new exception to the one being handled. `from None` turns it off.

**Next → Lesson 06: the loop.**
