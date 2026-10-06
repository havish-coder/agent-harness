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

Handlers must not raise: an exception in a handler aborts the turn (and rolls it back).
