# Lesson 05 · The Provider Adapter

> **Module 1: The Agent Loop** · Condensed lesson. All of Ollama's quirks get locked into
> one file, behind one interface.

## Key ideas

**1. The interface is one method.** Anything that can do this is a provider:

```python
class Provider(Protocol):
    model: str
    def chat(self, messages: list[Message], tools: list[dict]) -> Reply: ...
```

It uses `Protocol` (structural typing), not inheritance: a class doesn't have to declare
it's a provider, it just needs a matching `chat` method. That's handy for test fakes
(Lesson 13).

**2. An adapter does three jobs:**

```
 to_ollama()    Message ──► Ollama JSON          (outgoing translation)
 chat()         HTTP, timeouts, errors ──► ProviderError
 from_ollama()  Ollama JSON ──► Reply            (incoming translation + clean-up)
```

**3. The edge is where you clean up.** `from_ollama()` absorbs model and vendor quirks so
the rest of the harness never sees them:

| Quirk | Fix in the adapter |
|---|---|
| Thinking leaks into `content` with `</think>` (Lesson 01) | strip everything up to `</think>` |
| `arguments` arrives as a JSON string | parse it; if invalid, keep it as `{"_unparsed": ...}` so the *tool* reports the error |
| tool call without an `id` | generate one |
| `done_reason: "length"` | becomes `stop_reason="max_tokens"` |
| HTTP errors, connection refused, timeouts | one exception type: `ProviderError`, with a human-readable message |

**4. Tools cost tokens on every call.** Measured: a plain "Say hi" used **15** input
tokens. The same call with **one** small tool schema attached used **153**. Ten tools would
be about 1,500 tokens **before the user says anything**, on every step of every task.
Keep tool descriptions short and only offer tools the task needs.

**5. `num_ctx=8192` by default.** Lesson 01 showed Ollama's default is 4,096, and tool
schemas plus file contents fill that fast. Doubling it costs some VRAM (more of the model
runs on the CPU), but silent truncation is worse.

## What we built

- `harness/providers/base.py`: the `Provider` protocol and `ProviderError`.
- `harness/providers/ollama.py`: `OllamaProvider`, about 90 lines. One persistent
  `httpx.Client`, which reuses the connection between calls and is faster than a new
  request each time.

## Try it

```bash
.venv\Scripts\python -c "from harness.messages import Message; from harness.providers.ollama import OllamaProvider; print(OllamaProvider().chat([Message.user('Say hi in 3 words.')], []))"
```

Then read `from_ollama()` and find where each quirk in the table above is handled.

## Quiz

1. Why should a provider raise one `ProviderError` instead of letting `httpx` exceptions through?
2. If arguments arrive as invalid JSON, why not raise an error right in the adapter?
3. Your agent has 15 tools and runs 10 steps. Roughly how many input tokens go just to tool schemas?

<details><summary>Answers</summary>

1. The loop and UI shouldn't know which HTTP library (or vendor) is underneath. One
   exception type means one `except` clause, whatever the backend.
2. Then the whole agent run would crash. Passing it through lets the tool return
   "invalid arguments", the model sees the error, and it can retry with proper JSON.
3. About 15 × 140 ≈ 2,100 tokens per call × 10 calls ≈ **21,000 tokens**, before counting
   any conversation.
</details>

**Next → Lesson 06: the loop.**
