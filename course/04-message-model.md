# Lesson 04 · The Message Model

> **Module 1: The Agent Loop** · Before building the loop, the harness gets its own
> vocabulary for conversations. That small decision stops vendor JSON from spreading through
> every file we write from now on.

## Learning objectives
By the end of this lesson you can:
1. Explain why a harness defines its own message format instead of using a vendor's.
2. Describe the four types in `harness/messages.py` and what each field is for.
3. Explain why `Reply` is separate from `Message`.
4. Map each vendor's stop reasons onto our three.
5. Use Python dataclasses well: `field(default_factory=...)`, `X | None`, `Literal`, and
   classmethod constructors, and know what they *don't* check.

---

## 1. Learn

### 1.1 The problem: vendor JSON everywhere

So far our scripts pass Ollama's JSON around directly: `reply["message"]["tool_calls"]`,
`call["function"]["arguments"]`. That's fine for a 100-line script. In a harness, many
parts need to read messages:

```
agent loop · tool executor · permission policy · CLI · web UI · session storage · compaction · tests
```

If all of them read Ollama JSON, adding OpenAI support means changing **all** of them,
because OpenAI's shape is different (Lesson 03, section 1.8). With N providers and M
components you get N × M places that know about vendor formats.

The fix is a **common internal format** plus one **adapter** per provider:

```
              WITHOUT an internal format                 WITH an internal format
   Ollama ──┬── loop                             Ollama ──adapter──┐
            ├── CLI                                                │      ┌── loop
            ├── policy          (N × M links)    OpenAI ──adapter──┼──────┼── CLI
   OpenAI ──┼── loop                                               │      ├── policy
            ├── CLI                           Anthropic ──adapter──┘      └── sessions
            └── ...                                         (N + M links)
```

The core speaks one language. Each adapter is the only code that knows its vendor's dialect.

### 1.2 What a message format has to capture

| Need | Field |
|---|---|
| Who is speaking | `role`: `system`, `user`, `assistant`, `tool` |
| What they said | `content` (text) |
| The model asking for tools | `tool_calls`: a list, because of parallel calls (Lesson 03) |
| Which request a result answers | `tool_call_id`, and `tool_name` (Ollama matches by name) |

Each `ToolCall` holds `id`, `name`, and `arguments`, which is **always a parsed `dict`**. The
adapter does the parsing (OpenAI sends a JSON *string*), so the rest of the harness never
has to.

### 1.3 Why `Reply` is separate from `Message`

One model call returns more than a message: also **why it stopped** and **how many tokens it
used**. Those facts are about *the call*, not the conversation:

```
Reply
├── message: Message        ← goes into the history, re-sent on every future call
├── stop_reason             ← used once by the loop, then discarded
└── usage: Usage            ← added to the cost counter, then discarded
```

If usage lived inside `Message`, we'd store it in the history and have to strip it before every
request. Keeping them separate keeps the history clean.

### 1.4 Normalising stop reasons

Every vendor names stop reasons differently. The loop needs only three answers: *done*,
*wants tools*, *was cut off*.

| Vendor | Finished | Wants tools | Hit the output limit |
|---|---|---|---|
| Ollama `done_reason` | `stop` | `stop` (!) | `length` |
| OpenAI `finish_reason` | `stop` | `tool_calls` | `length` |
| Anthropic `stop_reason` | `end_turn` | `tool_use` | `max_tokens` |
| **ours: `stop_reason`** | **`end`** | **`tool_calls`** | **`max_tokens`** |

Note Ollama says `stop` even when the reply contains tool calls, so our adapter decides
`tool_calls` by checking whether any calls are present (Lesson 05).

### 1.5 Tool call IDs link requests to results

```
assistant: tool_calls = [ ToolCall(id="c1", name="get_current_time"),
                          ToolCall(id="c2", name="read_file", {"path": "notes.txt"}) ]
tool:      tool_call_id="c1"  "Monday 05 October 2026, 11:56"
tool:      tool_call_id="c2"  "TODO: buy milk ..."
```

With parallel calls the ID is what matches each result to its request. Ollama doesn't strictly
need it, but OpenAI and Anthropic do, so our format **always** carries it. If a provider
doesn't supply an ID, the adapter generates one.

### 1.6 Python tools used in `messages.py`

**`@dataclass`** writes the boring code for you: `__init__`, a readable `__repr__`, and
`__eq__` (two messages with equal fields are equal).

**`field(default_factory=list)`.** A default value of `[]` would be created **once** and shared
by every instance, the classic Python mutable-default bug. `default_factory=list` makes a
fresh list per message. Dataclasses refuse `= []` outright with a `ValueError` to protect you.

**`str | None`** (Python 3.10+) means "a string, or `None`". `tool_call_id` is only set on
tool messages.

**`Literal["system", "user", "assistant", "tool"]`** documents the allowed values, and editors
and type checkers flag typos. **But it is not checked at runtime:** `Message("assitant")` runs
without complaint. Type hints are documentation, not validation. That's why we validate
data at the **edges** (adapters, tool arguments in Lesson 09) and keep the core simple.

**Classmethod constructors** make call sites read like English and prevent mistakes:
```python
Message.tool_result(call, "TODO: buy milk")
# instead of
Message("tool", "TODO: buy milk", tool_call_id=call.id, tool_name=call.name)  # easy to forget a field
```

---

## 2. Build

### `harness/messages.py`, walkthrough

```python
Role = Literal["system", "user", "assistant", "tool"]
StopReason = Literal["end", "tool_calls", "max_tokens"]
```
Named type aliases. They're used in annotations, so readers see the allowed values at a glance.

```python
@dataclass
class ToolCall:
    id: str          # links this request to its result; some APIs require it
    name: str
    arguments: dict
```
The model's request. No `function` wrapper and no `index`: those were Ollama details,
and the adapter strips them.

```python
@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # assistant messages only
    tool_call_id: str | None = None                            # tool messages only
    tool_name: str | None = None                               # tool messages only
```
One class for all four roles. Fields that don't apply stay at their defaults. An
alternative design is one class per role (`UserMessage`, `ToolMessage`...). That's more type-safe
but more code. One class with optional fields is the common choice for harnesses.

```python
    @classmethod
    def tool_result(cls, call: ToolCall, content: str) -> "Message":
        return cls("tool", content, tool_call_id=call.id, tool_name=call.name)
```
Copies the ID and name from the call, so a result can't be accidentally mismatched.

```python
@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

@dataclass
class Reply:
    message: Message
    stop_reason: StopReason
    usage: Usage
```
What every provider's `chat()` returns (Lesson 05). `Usage` also works as a running total in
the agent (Lesson 06).

The file has **no logic and no imports beyond the standard library**. It's the foundation every
other module imports, so it must stay small and stable.

---

## 3. Understand: experiments

Start an interactive Python session with the harness importable:
```bash
.venv\Scripts\python
```

### Experiment 1: Build Lesson 03's conversation in our format
```python
from dataclasses import asdict
from harness.messages import Message, ToolCall

call = ToolCall(id="c1", name="read_file", arguments={"path": "notes.txt"})
history = [
    Message.system("You are helpful."),
    Message.user("How many TODOs are in notes.txt?"),
    Message("assistant", tool_calls=[call]),
    Message.tool_result(call, "TODO: buy milk"),
]
for m in history:
    print(asdict(m))
```
Compare with the raw Ollama JSON from Lesson 03. What's missing? (`function`, `index`.)
What's added? (`tool_call_id` on the result.)

### Experiment 2: Type hints are not validation
```python
Message("assitant", "typo in the role")
```
No error. Python doesn't enforce `Literal` at runtime. Now imagine this message reaching Ollama.
Where should such mistakes be caught? (At the edges, by code that validates.)

### Experiment 3: Why `default_factory`
```python
from dataclasses import dataclass
@dataclass
class Bad:
    items: list = []
```
Dataclasses raise `ValueError: mutable default ... use default_factory`. Here's the bug
it prevents, using a plain function:
```python
def add(item, items=[]):
    items.append(item)
    return items
add("a"); print(add("b"))   # ['a', 'b']: the default list is shared between calls!
```

### Experiment 4: Equality comes for free
```python
Message.user("hi") == Message.user("hi")    # True: compares field by field
```
This makes tests easy: compare whole messages instead of field by field (Lesson 13).

---

## 4. Review

### Quiz
1. With 3 providers and 6 components, how many "places that know a vendor format" exist
   without an internal format? With one?
2. Why is `stop_reason` on `Reply` rather than on `Message`?
3. Ollama reports `done_reason: "stop"` for a reply with tool calls. How do we still get
   `stop_reason == "tool_calls"`?
4. `Message("assitant")` doesn't raise an error. So where should invalid data be caught?
5. Why does `ToolCall.arguments` hold a `dict` even though OpenAI sends a string?

### Exercise 1: A translator to OpenAI's format
Write `to_openai(m: Message) -> dict` that converts our `Message` to OpenAI's chat format:
- tool calls become `{"id", "type": "function", "function": {"name", "arguments": <JSON string>}}`
- tool results become `{"role": "tool", "tool_call_id", "content"}`

(This is a preview of Lesson 14's second provider.)

### Exercise 2: An `assistant` constructor
Add `Message.assistant(text, tool_calls=None)` so building fake model replies in tests is one
short line.

### Checkpoint
Explain to yourself why the agent loop (Lesson 06) will never contain the word `"function"`
or `"done_reason"`.

---

### Answers

<details><summary>Quiz answers</summary>

1. Without: 3 × 6 = **18**. With: **3** (one adapter per provider). The 6 components only
   know our format.
2. It's a fact about one call, used once by the loop. History is re-sent on every call and
   should hold only what the model needs to read.
3. The adapter checks whether `tool_calls` is non-empty and sets `"tool_calls"` itself,
   whatever Ollama's `done_reason` says.
4. At the edges: in the provider adapter (data coming from the model) and in tool-argument
   validation (Lesson 09). The core trusts the types because the edges checked them.
5. Parsing happens once, in the adapter. If the string is invalid JSON, it's dealt with there,
   and everything after it can rely on a `dict`.
</details>

<details><summary>Exercise answers</summary>

**1.**
```python
import json

def to_openai(m: Message) -> dict:
    out = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {"id": c.id, "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in m.tool_calls
        ]
    if m.role == "tool":
        out["tool_call_id"] = m.tool_call_id
    return out
```

**2.**
```python
    @classmethod
    def assistant(cls, text: str = "", tool_calls: list[ToolCall] | None = None) -> "Message":
        return cls("assistant", text, tool_calls=tool_calls or [])
```
</details>

### Glossary
- **Internal (canonical) format**: the one data shape the core of a system uses, whatever the outside sources.
- **Adapter**: code that converts between an external format and the internal one.
- **Dataclass**: a Python class whose `__init__`, `__repr__` and `__eq__` are generated from its fields.
- **Mutable default**: a default value like `[]` that would be shared between instances or calls.
- **Type hint**: an annotation for humans and tools. Not enforced when the program runs.

**Next → Lesson 05: the provider adapter.**
