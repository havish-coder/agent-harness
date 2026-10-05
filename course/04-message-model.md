# Lesson 04 · The Message Model

> **Module 1: The Agent Loop** · Condensed lesson. The harness gets its own vocabulary,
> so no vendor's JSON leaks into the core.

## Key ideas

**1. Why not just use Ollama's JSON everywhere?** Because every vendor's JSON differs
(Lesson 02): `message` vs `choices[0].message`, arguments as an object vs a string, tool
results matched by `tool_name` vs `tool_call_id`. If the loop, the UI and the security
checks all read Ollama JSON directly, adding a second provider means rewriting all of them.
The fix is the oldest trick in software design:

```
             the harness core speaks ONE language
   ┌───────────────────────────────────────────────────────┐
   │  agent loop · tools · policy · UI · sessions          │
   │          (uses only Message / ToolCall / Reply)       │
   └───────────────┬───────────────────────┬───────────────┘
                   │ adapter               │ adapter
             Ollama JSON              OpenAI JSON  (...Anthropic, Gemini)
```

**2. Four small types** in `harness/messages.py`:

| Type | Represents |
|---|---|
| `Message` | one entry in the conversation: `role`, `content`, plus `tool_calls` (assistant) or `tool_call_id`/`tool_name` (tool) |
| `ToolCall` | the model asking for a tool: `id`, `name`, `arguments` (always a parsed `dict`) |
| `Usage` | tokens in/out for one call |
| `Reply` | what one model call returns: the assistant `Message`, a `stop_reason`, and `Usage` |

**3. `stop_reason` is normalised.** Vendors say `"stop"`, `"length"`, `"tool_use"`,
`"end_turn"`... We reduce it to three cases the loop cares about:
`"end"` (final answer), `"tool_calls"` (run tools), `"max_tokens"` (cut off: be careful).

**4. Tool call IDs link requests to results.** When the model makes two calls in parallel,
the ID says which result answers which call. Ollama doesn't strictly need it, but OpenAI
and Anthropic do, so our format always carries it.

**5. Dataclasses, not dicts.** `msg.tool_calls` instead of `msg.get("tool_calls", [])`.
Typos become errors at once instead of silent `None`s, and your editor can autocomplete.

## What we built

`harness/messages.py`, about 60 lines, no logic, just shapes. Helper constructors keep call
sites readable:

```python
Message.system("You are helpful.")
Message.user("How many TODOs?")
Message.tool_result(call, "TODO: buy milk")   # copies call.id and call.name for you
```

## Try it

```bash
.venv\Scripts\python -c "from harness.messages import *; c = ToolCall('c1', 'read_file', {'path': 'notes.txt'}); print(Message.tool_result(c, 'TODO: buy milk'))"
```

## Quiz

1. What breaks if the agent loop reads Ollama's JSON directly?
2. Why does `ToolCall.arguments` always hold a `dict`, even though OpenAI sends a string?
3. Why does the loop need `"max_tokens"` as a separate stop reason?

<details><summary>Answers</summary>

1. Every other provider would need its own copy of the loop, UI and security code. Vendor
   details would spread through the whole codebase.
2. Converting is the adapter's job. Parsing (and failing) happens once, at the edge, so the
   rest of the harness can trust the type.
3. A cut-off reply may contain a half-written tool call or an incomplete answer. The loop
   must not treat it like a normal final answer.
</details>

**Next → Lesson 05: the provider adapter.**
