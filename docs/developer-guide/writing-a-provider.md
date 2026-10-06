# Writing a provider

A provider connects the agent to one model API. It translates between the harness's message
types (`harness/messages.py`) and the vendor's JSON, in both directions.

## The interface
```python
class MyProvider:
    model: str

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply: ...

    # optional: makes answers appear as they are generated
    def stream(self, messages: list[Message], tools: list[dict]) -> Iterator[TextDelta | ThinkingDelta | Reply]: ...
```

- `tools` are neutral schemas: `{"name", "description", "parameters"}`. Wrap them in the
  vendor's format.
- `chat()` returns a `Reply`: the assistant `Message` (text and/or `ToolCall`s), a
  `stop_reason` (`end`, `tool_calls` or `max_tokens`) and `Usage`.
- `stream()` yields `TextDelta`/`ThinkingDelta` pieces as they arrive and the complete `Reply`
  **last**. Open the HTTP response in a `with` block so that closing the generator (Ctrl+C)
  closes the connection and the server stops generating.

## Rules
1. **Never let vendor JSON escape the adapter.** Everything outside `harness/providers/` sees
   only `Message`, `ToolCall` and `Reply`.
2. **Turn every failure into `ProviderError`** with `status` and `retryable`: 408, 429 and 5xx
   are usually worth retrying, other 4xx are not. Pass `retry_after` when the server sends a
   `Retry-After` header.
3. **Tolerate malformed tool arguments.** If the model's arguments aren't valid JSON, return
   `{"_unparsed": raw}` instead of raising; the tool then fails with a clear error the model can
   correct.
4. **Never print or log API keys.** Keep them out of `repr()`, error messages and tracebacks.
5. **Accept a `transport=`** argument and pass it to `httpx.Client`, so tests can use
   `httpx.MockTransport`.

## Testing
Test the wire format without a server, as in `tests/test_openai_provider.py`:

```python
def server(handler):
    return MyProvider("m", transport=httpx.MockTransport(handler))

provider = server(lambda request: httpx.Response(200, json={...}))
reply = provider.chat([Message.user("hi")], [])
```

Cover: the request body for a whole conversation (system, user, assistant tool calls, tool
results), a text reply, a tool-call reply, streamed text, streamed tool calls, cut-off replies,
HTTP errors (retryable or not) and an error in the middle of a stream.

## Registering it
Add it to `harness/providers/factory.py` (`make_provider`) so `--provider` can select it.
