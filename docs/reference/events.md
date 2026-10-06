# Events reference

The agent loop reports progress through a callback passed as `on_event`:

```python
def on_event(kind: str, data) -> None: ...
agent = Agent(provider, tools, system_prompt, on_event=on_event)
```

| `kind` | `data` | Emitted when |
|---|---|---|
| `text_delta` | `str` | a piece of the model's answer arrived (streaming providers only) |
| `thinking_delta` | `str` | a piece of a thinking model's reasoning arrived (with `--think`) |
| `model_reply` | `Reply` | the model's message is complete (with or without tool calls) |
| `tool_call` | `ToolCall` | right before a tool runs |
| `tool_denied` | `ToolCall` | the approver refused a call; the model receives a denial message instead of a result |
| `tool_result` | `(ToolCall, str)` | after every call, run or not; the string is exactly what the model will read |

## Stop reasons
After `run()` returns or raises, `agent.stop_reason` says why the turn ended:

| Value | Meaning |
|---|---|
| `completed` | the model gave a final answer |
| `max_steps` | the step limit was reached first |
| `max_tokens` | the final answer was cut off by the output-token limit |
| `cancelled` | Ctrl+C (`KeyboardInterrupt`); the turn was rolled back |
| `error` | an exception (e.g. the model server failed); the turn was rolled back |

While a reply streams, `text_delta` events arrive in order and always before that reply's
`model_reply`. Text the model writes *before* asking for tools is streamed too.

When one reply contains several calls, `tool_call` is emitted for every call in a batch
before the batch runs, and `tool_result` for each afterwards, in the order the model asked.
All events are emitted from the thread that called `run()`.

Handlers must not raise: an exception in a handler aborts the turn (and rolls it back).
