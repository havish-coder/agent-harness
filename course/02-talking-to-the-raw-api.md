# Lesson 02 · Talking to the Raw API

> **Module 0: Foundations** · Condensed lesson. An LLM is just an HTTP server. We call
> it by hand, read every field, stream tokens, and build the world's smallest harness.

## Key ideas

**1. One call = one HTTP POST.** Ollama listens on `http://localhost:11434`. A chat is
`POST /api/chat` with a JSON body:

```json
{ "model": "qwen3:4b-instruct",
  "messages": [{"role": "user", "content": "Say hi in 3 words."}],
  "stream": false,
  "options": {"num_ctx": 4096, "temperature": 0.7, "num_predict": 100} }
```

**2. The response carries the reply and the metrics.** Real output from your machine:

```json
{ "message": {"role": "assistant", "content": "Hello there friend!"},
  "done": true,
  "done_reason": "stop",           ← "stop" = finished naturally, "length" = hit num_predict
  "prompt_eval_count": 15,         ← input tokens
  "prompt_eval_cached_count": 1,   ← input tokens reused from cache
  "eval_count": 5,                 ← output tokens
  "eval_duration": 164886000,      ← nanoseconds! 5 / 0.165 s = 30 tokens/s
  "load_duration": 34284000 }
```

**3. Streaming = NDJSON.** With `"stream": true` the server sends one JSON object per line
as each token is produced. The last line has `"done": true` and the metrics:

```text
{"message":{"content":"1"},"done":false}
{"message":{"content":"  \n"},"done":false}
{"message":{"content":"2"},"done":false}
...
{"message":{"content":""},"done":true,"done_reason":"stop","eval_count":6,...}
```

Why stream? **Time to first token** was 0.29 s on your machine. Without streaming, the user
stares at nothing until the whole answer is done. Cloud APIs stream too, but use **SSE**
(`data: {...}` lines) instead of NDJSON. Same idea, different framing.

**4. Things that go wrong, and how they look:**

| Failure | What you get | Harness should... |
|---|---|---|
| Ollama not running | `ConnectError` | say so clearly |
| Wrong model name | HTTP 404 `{"error":"model 'nope:1b' not found"}` | show the server's message |
| Model too slow | `TimeoutException` | use a long *read* timeout, short *connect* timeout |
| Output cut off | `done_reason: "length"` | detect it, because a cut-off tool call is broken JSON |
| Error mid-stream | HTTP 200, then a line `{"error": "..."}` | check every chunk, not just the status code |

**5. Same model, different dialect.** Ollama also serves the OpenAI format at
`/v1/chat/completions`. Same reply, different JSON shape:

| Concept | Ollama native | OpenAI-compatible |
|---|---|---|
| reply text | `message.content` | `choices[0].message.content` |
| why it stopped | `done_reason` | `choices[0].finish_reason` |
| input tokens | `prompt_eval_count` | `usage.prompt_tokens` |
| output tokens | `eval_count` | `usage.completion_tokens` |

Every provider differs like this. That's why Lesson 05 builds a **provider adapter**.

## What we built: `scripts/raw_ollama.py`

| Mode | What it shows |
|---|---|
| `once` | prints the exact request and full response JSON |
| `stream` | tokens appear live; `--show-chunks` prints the raw NDJSON |
| `chat` | multi-turn: **we** keep `history` and re-send it every turn |
| `openai` | the same call through the OpenAI-compatible endpoint |

Key code to read:
- `TIMEOUT = httpx.Timeout(300, connect=10)`: the default HTTP timeout (5 s) is far too
  short for an LLM.
- `stream_reply()`: `iter_lines()` → `json.loads()` each line → print with `flush=True`.
- `chat()`: the whole "memory" is a Python list. `/fake` appends an assistant message the
  model never wrote.

## Try it

```bash
.venv\Scripts\python scripts\raw_ollama.py once "Say hi in 3 words."
```
```bash
.venv\Scripts\python scripts\raw_ollama.py stream "Write a long poem about rain" --max-tokens 15
```
```bash
.venv\Scripts\python scripts\raw_ollama.py chat
```

In chat mode, try this:
1. Have a 3-turn conversation and watch **prompt tokens** grow each turn (the history is re-sent).
2. `/fake I secretly love pineapple pizza.` then ask *"What do you secretly love?"*
   When we tested it, the model happily owned a statement it never made. **The model trusts
   whatever history the harness gives it.** That's useful (compaction, Module 5) and
   dangerous (anyone who can tamper with history controls the agent).
3. `/history` shows exactly what gets sent.

## Quiz

1. You see `done_reason: "length"` while the model was writing a tool call. What happened, and what should the harness do?
2. Why a short *connect* timeout but a long *read* timeout?
3. The `/fake` experiment: who really controls what the model "remembers"?

<details><summary>Answers</summary>

1. It hit the output token limit (`num_predict`) mid-generation, so the tool call JSON is
   incomplete. The harness should treat it as an error, never run a half-parsed call, and
   either raise the limit and retry or tell the model its output was cut off.
2. Connecting to a local server should take milliseconds, so failing fast means the server is
   down. Generating can legitimately take minutes on a slow GPU.
3. The harness. The model has no memory of its own; it believes whatever `messages[]`
   contains, including messages it never wrote.
</details>

**Next → Lesson 03: Tool calling on the wire.**
