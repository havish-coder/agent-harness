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
| `model_reply` | `Reply` | the model's message is complete (with or without tool calls); `Reply.usage` has the token counts, including `cache_read_tokens` and `cache_write_tokens`, and `Reply.model` the model that answered |
| `model_call` | `int` | right before each model call; the number of messages being sent |
| `tool_call` | `ToolCall` | the model asked for this call (emitted before it is checked or run) |
| `permission` | `(ToolCall, Decision)` | the permission decision for a call: `Decision.action` is `allow`, `ask` or `deny`, `Decision.reason` says why ([permissions](../user-guide/permissions.md)) |
| `hook` | `(event, ToolCall or None, HookResult)` | a [hook](../user-guide/hooks.md) answered, added context or failed; `event` is `user_prompt_submit`, `pre_tool_use` or `post_tool_use` |
| `tool_approved` | `(ToolCall, answer)` | the user said yes (`True`) or "always" to a question |
| `redacted` | `(ToolCall, [kinds])` | secrets were found and hidden in a tool result |
| `limit` | `str` | a session limit was reached; the string says which |
| `context` | `ContextStatus` | before each model call: the estimated size of the conversation, the limit, and `level` (`ok`, `warn`, `critical`, `full`) |
| `microcompact` | `MicroResult` | the window was filling and old tool results were replaced by notes; `.cleared` lists them and `.saved` is the estimated tokens given back ([context](../user-guide/context.md#when-the-window-fills-clearing-old-results)) |
| `compacting` | `int` | the harness is about to ask the model to summarise this many older messages ([context](../user-guide/context.md#summarising-the-conversation-compact)) |
| `compact` | `Compaction` | the older messages were replaced by a summary; `.removed`, `.before` and `.after` (estimated tokens), `.fenced` (marked untrusted) |
| `compact_failed` | `str` | the model could not write a summary (an error, or an empty one); the conversation is unchanged |
| `tool_refused` | `(ToolCall, str)` | the permissions denied a call (a deny rule, plan mode, a path outside the workspace); the string is the reason |
| `tool_denied` | `ToolCall` | the user answered no; the model receives a denial message instead of a result |
| `tool_result` | `(ToolCall, str)` | after every call, run or not; the string is exactly what the model will read |

## Stop reasons
After `run()` returns or raises, `agent.stop_reason` says why the turn ended:

| Value | Meaning |
|---|---|
| `completed` | the model gave a final answer |
| `max_steps` | the step limit was reached first |
| `max_tokens` | the final answer was cut off by the output-token limit |
| `context_full` | the conversation wouldn't fit the model's window, so the model wasn't called ([context](../user-guide/context.md)) |
| `limit` | a session limit (tool calls, cost, tokens, minutes) was reached; the model wasn't called again |
| `blocked` | a `user_prompt_submit` hook refused the message; the model was never called and nothing was added to the conversation |
| `cancelled` | Ctrl+C (`KeyboardInterrupt`); the turn was rolled back |
| `error` | an exception (e.g. the model server failed); the turn was rolled back |

While a reply streams, `text_delta` events arrive in order and always before that reply's
`model_reply`. Text the model writes *before* asking for tools is streamed too.

When one reply contains several calls, `tool_call` is emitted for every call in a batch
before the batch runs, and `tool_result` for each afterwards, in the order the model asked.
All events are emitted from the thread that called `run()`, and every question to the user is
asked from it too: the calls of a batch are checked and decided first, then the allowed ones run.

Handlers must not raise: an exception in a handler aborts the turn (and rolls it back).
