# Events reference

The agent loop reports progress through a callback passed as `on_event`:

```python
def on_event(kind: str, data) -> None: ...
agent = Agent(provider, tools, system_prompt, on_event=on_event)
```

| `kind` | `data` | Emitted when |
|---|---|---|
| `model_reply` | `Reply` | the model returned a message (with or without tool calls) |
| `tool_call` | `ToolCall` | right before a tool runs |
| `tool_result` | `(ToolCall, str)` | right after a tool ran; the string is what the model will read |

Handlers must not raise: an exception in a handler aborts the turn (and rolls it back).
