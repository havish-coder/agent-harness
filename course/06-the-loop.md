# Lesson 06 · The Loop

> **Module 1: The Agent Loop** · Lesson 03's three manual steps become a loop, and the
> model starts planning its own steps. This is the heart of the harness: about 40 lines that
> everything else plugs into.

## Learning objectives
By the end of this lesson you can:
1. Write the agent loop from memory, including both stop conditions.
2. Trace how `messages` and token counts grow during a multi-step task.
3. Explain each design decision: step limit, errors as results, unknown-tool messages,
   rollback, event callbacks, usage accounting.
4. Drive the loop with a **scripted fake model** to test behaviour deterministically.

---

## 1. Learn

### 1.1 From three steps to a loop

Lesson 03 had a fixed script: ask, run tools, ask again. But the model might want tools
**again** after seeing the results, and again after that. We can't know in advance how many
rounds a task needs, so we loop until the model stops asking:

```
                 ┌──────────────────────────────────────────┐
                 ▼                                          │
   user ──► [ call model ] ──► tool calls? ── yes ──► [ run each tool ] ──► append results
                 │                   │
                 │                   no
                 │                   ▼
                 │             return the answer        (stop #1: the model is done)
                 │
           step limit reached ──► return "(stopped...)"  (stop #2: safety net)
```

```python
for _ in range(self.max_steps):                      # stop #2
    reply = self.provider.chat(self.messages, schemas)
    self.messages.append(reply.message)
    if not reply.message.tool_calls:                 # stop #1
        return reply.message.content
    for call in reply.message.tool_calls:
        result = self.execute(call)
        self.messages.append(Message.tool_result(call, result))
return "(stopped: reached the limit ...)"
```

### 1.2 Watching it work: a real trace

*"Find the recipe in my workspace and tell me how many eggs I need."* Measured on your machine:

| Call | Input tokens | Model decided |
|---|---:|---|
| 1 | 285 | `list_dir(path='recipes/')`: it guessed the folder from the word "recipe" |
| 2 | 328 | `read_file(path='recipes/pancakes.md')` |
| 3 | 421 | final answer: *"The recipe for pancakes requires 1 egg."* |

`messages` at the end: `system, user, assistant, tool, assistant, tool, assistant`, 7 messages.

Three things to notice:
- **Nobody told it which file.** It chose its steps from the results. That's the difference
  between an agent and a chatbot with tools.
- **Input tokens grow every call** (285 → 328 → 421) because the whole history is re-sent
  (Lesson 01's quadratic cost, live).
- **Runs vary.** An earlier identical run first listed the root (`.`), then `recipes/`, then
  read the file: 4 calls and 1,281 tokens in total. Same question, different plan. Models are
  probabilistic, so test behaviour over several runs.

### 1.3 The two stop conditions

| Stop | When | Protects against |
|---|---|---|
| **#1 no tool calls** | the model answers in plain text | nothing; this is the normal finish |
| **#2 `max_steps`** | the loop ran `max_steps` times (default 10) | a confused model calling tools forever, burning time and tokens |

A third exit is an **exception** (model server down, Ctrl+C). Section 1.6 covers it.
Truncation gets special handling: if the final reply was cut off (`stop_reason ==
"max_tokens"`), the loop appends a notice so the user knows the answer is incomplete.

### 1.4 Errors as results: the self-correction loop

`execute()` never raises. Every failure becomes text the model reads on its next call:

| What went wrong | Text the model receives |
|---|---|
| unknown tool name | `Error: unknown tool 'delete_everything'. Available tools: list_dir, read_file` |
| wrong argument name | `Error: TypeError: ... read_file() got an unexpected keyword argument 'file'` |
| the tool itself failed | `Error: FileNotFoundError: ...` |

A real recovery from your machine (Lesson 07's first test run):
```
→ list_dir(path='notes.txt')       Error: NotADirectoryError: ... The directory name is invalid
→ read_file(path='notes.txt')      TODO: buy milk ...            ← the model fixed its own mistake
agent> There are 3 TODOs.
```

The unknown-tool message **lists the real tools**. Small models invent plausible names
(`read_text`, `open_file`), and naming the valid options lets them correct themselves on the
next step.

### 1.5 Tools run one after another

When the model asks for several tools in one reply, we run them **sequentially**, in order.
Running them in parallel (threads or async) is faster, but harder to reason about: two tools
writing the same file, or a permission prompt in the middle (Lesson 19). Correctness first.

### 1.6 Rollback: keeping history consistent

Suppose the model asks for `list_dir`, we append its request, and then the server crashes, or
you press **Ctrl+C**, before the result is appended. The history now ends with a request that
has no result:

```
system, user, assistant(tool_calls=[list_dir]) ✗ no tool result
```

The next request built from that history is **malformed**. OpenAI rejects it with an error
(*an assistant message with tool_calls must be followed by tool messages*). Other models get
confused.

So `run()` remembers where the turn started and deletes everything from that point if
anything goes wrong:

```python
turn_start = len(self.messages)
...
except BaseException:
    del self.messages[turn_start:]   # back to the state before this user message
    raise                            # still report the error to the caller
```

It's **`BaseException`**, not `Exception`, because `KeyboardInterrupt` (Ctrl+C) isn't a
subclass of `Exception`. A plain `except Exception` would miss exactly the case we care about.

### 1.7 Events: the loop doesn't print

The loop reports what happens through a callback, `on_event(kind, data)`:

| Event | Data | Who might use it |
|---|---|---|
| `model_reply` | `Reply` | token counters, debug logs |
| `tool_call` | `ToolCall` | the CLI shows `→ read_file(path='notes.txt')` |
| `tool_result` | `(ToolCall, str)` | the CLI shows a preview; an audit log stores it (Lesson 24) |

This is the **observer pattern**. The CLI prints with colours, the web UI (Module 6) will send
events over the network, and tests can collect them in a list, all without changing
`agent.py`. The default handler does nothing: `lambda kind, data: None`.

### 1.8 Usage accounting

`self.usage` adds up input and output tokens over **every** call the agent makes. One user
question can mean several model calls, and this is the true cost of a task. The CLI shows the
difference per turn: `[1007 input + 196 output tokens]`.

### 1.9 A correction: history vs. prompt

When we first built this lesson, we asked a follow-up in the same conversation (*"What was
the total revenue in the sales data?"*), and the model answered *"I don't have access to any
sales data"* without calling a tool. We blamed the **history**. Lesson 07's measurements showed
the **system prompt** mattered more: with the right prompt, follow-ups worked 12 times out of
12. History does have *some* effect: with a weaker prompt, follow-ups succeeded less often than
fresh questions (2/6 vs. 4/6). Both matter. **Measure before you conclude.**

---

## 2. Build

### `harness/tools/base.py`
```python
@dataclass
class Tool:
    name: str
    description: str        # a prompt: tells the model WHEN and HOW to use the tool
    parameters: dict        # JSON Schema for the arguments
    fn: Callable[..., str]  # the real function; must return text for the model to read

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}
```
Lesson 03's `TOOLS` entry and `FUNCTIONS` entry, joined into one object: the description
and the code can't drift apart. `schema()` produces the neutral shape the provider expects
(Lesson 05).

### `harness/agent.py`, walkthrough

**`__init__`**: stores the provider, turns the tool list into a dict keyed by name (fast
lookup, and easy to check for unknown names), sets `max_steps`, the event handler (or a no-op
default), and a zeroed `Usage`. Then calls `reset()`.

**`reset()`**: the history becomes just the system prompt. "Forgetting" is simply deleting
the list. The model never remembered anything.

**`run(user_input)`**:
1. Remember `turn_start`, append the user message, and build tool schemas once for this turn.
2. Loop up to `max_steps` times: call the model, add up usage, append its message, emit
   `model_reply`.
3. No tool calls? Return the text (with a cut-off notice if `max_tokens`).
4. Otherwise, for each call: emit `tool_call`, `execute()`, emit `tool_result`, append
   `Message.tool_result()`.
5. Out of steps? Return the "stopped" message.
6. Any exception: roll back to `turn_start` and re-raise.

**`execute(call)`**: look the tool up (unknown → error listing the valid names), call
`tool.fn(**call.arguments)`, and convert any exception into `Error: <Type>: <message>`. `str()`
around the result makes sure the model always receives text.

---

## 3. Understand: experiments

Start Python with `.venv\Scripts\python` and paste the snippets.

### Experiment 1: Trace a real run
```python
from pathlib import Path
from harness.agent import Agent
from harness.providers.ollama import OllamaProvider
from harness.tools.fs import make_fs_tools

def trace(kind, data):
    if kind == "model_reply":
        what = [f"{c.name}({c.arguments})" for c in data.message.tool_calls] or "FINAL ANSWER"
        print(f"input={data.usage.input_tokens:5}  ->  {what}")

agent = Agent(OllamaProvider(), make_fs_tools(Path("workspace").resolve()),
              "You are a helpful agent. Use tools to inspect the workspace; never guess file contents.",
              on_event=trace)
print(agent.run("Find the recipe in my workspace and tell me how many eggs I need."))
print([m.role for m in agent.messages])
```
Run the `agent.run(...)` line 2–3 more times (call `agent.reset()` first). Does it plan the
same steps each time?

### Experiment 2: A scripted fake model
Real models are random. To test the *loop*, replace the model with a script:
```python
from harness.messages import Message, Reply, ToolCall, Usage

class ScriptedProvider:
    """A fake model: returns pre-written replies in order. No GPU, no randomness."""
    model = "scripted"
    def __init__(self, replies): self.replies = list(replies)
    def chat(self, messages, tools): return self.replies.pop(0)

def calls(*tc): return Reply(Message("assistant", tool_calls=list(tc)), "tool_calls", Usage())
def final(text): return Reply(Message("assistant", text), "end", Usage())

fake = ScriptedProvider([
    calls(ToolCall("1", "delete_everything", {})),               # a tool that doesn't exist
    calls(ToolCall("2", "read_file", {"file": "notes.txt"})),    # wrong argument name
    calls(ToolCall("3", "read_file", {"path": "notes.txt"})),    # correct
    final("There are 3 TODOs."),
])
show = lambda kind, data: print(kind, repr(data[1][:90])) if kind == "tool_result" else None
agent = Agent(fake, make_fs_tools(Path("workspace").resolve()), "test", on_event=show)
print(agent.run("How many TODOs?"))
```
Expected:
```text
tool_result "Error: unknown tool 'delete_everything'. Available tools: list_dir, read_file"
tool_result "Error: TypeError: make_fs_tools.<locals>.read_file() got an unexpected keyword argument 'f"
tool_result 'TODO: buy milk\nDONE: fix bike\nTODO: email Sam about the project\nTODO: study lesson 03\nDONE'
There are 3 TODOs.
```
The `ScriptedProvider` has no HTTP code at all. It satisfies `Provider` just by having
`model` and `chat()` (Lesson 05's `Protocol`). Lesson 13 turns this idea into a proper test suite.

### Experiment 3: The step limit
```python
class LoopingProvider:
    model = "loop"
    def chat(self, messages, tools): return calls(ToolCall("x", "list_dir", {"path": "."}))

print(Agent(LoopingProvider(), make_fs_tools(Path("workspace").resolve()), "test", max_steps=3).run("hi"))
```
Expected: `(stopped: reached the limit of 3 steps without a final answer)`. Without `max_steps`,
this would run forever.

### Experiment 4: Rollback
```python
class FailsOnSecondCall:
    model = "fail"
    def __init__(self): self.n = 0
    def chat(self, messages, tools):
        self.n += 1
        if self.n == 2:
            raise RuntimeError("server crashed")
        return calls(ToolCall("y", "list_dir", {"path": "."}))

a = Agent(FailsOnSecondCall(), make_fs_tools(Path("workspace").resolve()), "test")
print(len(a.messages))          # 1 (just the system prompt)
try:
    a.run("hi")
except RuntimeError as e:
    print("error:", e)
print([m.role for m in a.messages])   # ['system']: the half-finished turn was removed
```

### Experiment 5: Ctrl+C in the real app
Run `.venv\Scripts\harness`, ask a question, and press **Ctrl+C** while it's working. You'll see
`(cancelled)`. Ask another question: it works normally, because the rollback kept the history valid.

---

## 4. Review

### Quiz
1. Name the two stop conditions and what each protects against.
2. Why do input tokens grow on every call within one task?
3. Why does `run()` catch `BaseException` instead of `Exception`?
4. What would go wrong without rollback?
5. Why does the loop emit events instead of printing?
6. The correct sales total is 2400+1900+2800+2200+3200+1800 = **14,300**. Why is it risky
   to trust a 4B model's arithmetic, and what could a harness give it instead?

### Exercise 1: Number the steps
Add a `"step"` event, emitted at the start of each loop iteration with the step number
(1, 2, 3...). Then make Experiment 1's `trace` print it.

### Exercise 2: Catch repeated calls
A stuck model often repeats the **same** call with the **same** arguments. Make `run()` stop
early with `"(stopped: the model repeated the same tool call)"` if a call is identical to the
previous one. (Module 4's Lesson 23 builds a fuller version.)

### Checkpoint
Close this file and write the loop from memory: both stop conditions, appending the reply,
executing tools, appending results.

---

### Answers

<details><summary>Quiz answers</summary>

1. **No tool calls**: the model's final answer, the normal finish. **`max_steps`**: stops an
   endless loop of tool calls that would burn time and tokens.
2. Each call re-sends the entire history, which now also includes the previous tool request
   and result. The model is stateless (Lesson 01).
3. `KeyboardInterrupt` (Ctrl+C) inherits from `BaseException`, not `Exception`. Catching only
   `Exception` would skip the rollback exactly when the user cancels.
4. The history could end with an assistant tool request that has no result. The next call
   would be malformed (OpenAI rejects it) or confuse the model.
5. So any interface (CLI, web UI, test, audit log) can react in its own way without changing
   the loop: the observer pattern.
6. Numbers are tokenized digit by digit and small models often make mistakes adding them. A
   calculator or code-execution tool lets exact code do the math.
</details>

<details><summary>Exercise answers</summary>

**1.** In `run()`:
```python
for step in range(1, self.max_steps + 1):
    self.on_event("step", step)
    reply = self.provider.chat(self.messages, schemas)
    ...
```
In `trace`: `if kind == "step": print(f"--- step {data}")`

**2.** In `run()`, before the loop: `last_call = None`. Replace the tool-execution part with:
```python
repeated = False
for call in reply.message.tool_calls:
    key = (call.name, json.dumps(call.arguments, sort_keys=True))
    if key == last_call:
        result = "Error: you already made this exact call. Stopping."
        repeated = True
    else:
        result = self.execute(call)
    last_call = key
    self.messages.append(Message.tool_result(call, result))   # every call still gets a result
if repeated:
    return "(stopped: the model repeated the same tool call)"
```
(Add `import json` at the top.) Note we **don't** `return` in the middle of the `for` loop:
that would leave tool calls without results, which is exactly the inconsistent history that
section 1.6 warns about.
</details>

### Glossary
- **Agent loop**: call the model, run the tools it asks for, append the results, repeat until it answers.
- **Self-correction**: the model fixing its own mistakes after reading error results.
- **Rollback**: undoing a partially completed operation so the state stays consistent.
- **Observer pattern**: an object announces events through callbacks without knowing who listens.
- **Test fake**: a stand-in for a real dependency (here, the model) that behaves predictably.

**Next → Lesson 07: first tools + the REPL.**
