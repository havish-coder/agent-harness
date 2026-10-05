# Lesson 03 · Tool Calling on the Wire

> **Module 0: Foundations** · The last foundations lesson. We do one complete
> tool-calling round trip **by hand**, printing every message, so nothing about tool use
> stays magic. Lesson 06 then turns these manual steps into the agent loop.

## Learning objectives
By the end of this lesson you can:
1. Write a tool definition in JSON Schema and explain what every field is for.
2. Trace a tool-calling round trip message by message, and say who writes each message.
3. Explain the rules for sending a tool result back, and why each exists.
4. Predict the four ways a model can respond when it has tools: one call, several calls,
   no call, or a failing call.
5. Spot the security problems in a naive tool implementation.

---

## 1. Learn

### 1.1 Why tools exist

Recall Lesson 00: a model is **isolated**. It can't see your files, the clock, the web, or
anything that happened after training. Tools are its **eyes and hands**. Modern models are
trained for **function calling**: given a list of available functions, they can reply with a
structured request ("please call `read_file` with `path=notes.txt`") instead of prose.

The model only *asks*. Your code decides whether to run the function and what to send
back. Every bit of real-world access goes through code you control.

### 1.2 Anatomy of a tool definition

```json
{
  "type": "function",                    ← (1) always "function" for Ollama/OpenAI
  "function": {
    "name": "read_file",                 ← (2) identifier the model writes back to you
    "description": "Read a text file from the user's workspace and return its contents.",  ← (3)
    "parameters": {                      ← (4) JSON Schema describing the arguments
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "File path relative to the workspace, e.g. notes.txt"   ← (5)
        }
      },
      "required": ["path"]               ← (6)
    }
  }
}
```

| # | Field | What it does | Tips |
|---|---|---|---|
| 1 | `type` | marks this as a function tool | always `"function"` here |
| 2 | `name` | the model copies this name into its request; you use it to look up the real function | short, `snake_case`, verb first: `read_file`, `list_dir` |
| 3 | `description` | **this is a prompt.** The model decides *when* and *how* to use the tool from this text alone | say what it does, when to use it, what it returns |
| 4 | `parameters` | a JSON Schema object: the shape of the arguments | always `"type": "object"` at the top |
| 5 | parameter `description` | how to fill in this argument | give an example value: "e.g. notes.txt" |
| 6 | `required` | arguments that must be present | leave optional ones out of this list |

JSON Schema has a small set of types you'll use constantly:

| JSON Schema | Python | Example |
|---|---|---|
| `"string"` | `str` | `"notes.txt"` |
| `"integer"` | `int` | `42` |
| `"number"` | `float` | `3.14` |
| `"boolean"` | `bool` | `true` |
| `"array"` + `"items"` | `list` | `["a", "b"]` |
| `"object"` + `"properties"` | `dict` | `{"x": 1}` |
| `"enum": [...]` | one of fixed values | `"asc"` or `"desc"` |

### 1.3 Where the definition really goes

In Lesson 01 you read the chat template. Ollama pastes every tool definition **as text into
the system prompt**, inside `<tools>...</tools>`, with instructions telling the model to answer
with `<tool_call>{json}</tool_call>`. Two consequences:
- Tool definitions cost **input tokens on every call** (Lesson 05 measures how many).
- The model reads names and descriptions **literally**. A vague description gets a tool
  used at the wrong time; a misleading one gets it misused.

### 1.4 The round trip, message by message

```
  YOU (harness)                                 MODEL
  ─────────────                                 ─────
  STEP 1  user question + tool definitions ───►
                                           ◄─── assistant: tool_calls=[read_file(notes.txt)]
                                                (content is empty: it "spoke" only via the call)
  STEP 2  run read_file("notes.txt") yourself
          → "TODO: buy milk\nDONE: fix bike\n..."
  STEP 3  history + tool request + result  ───►
                                           ◄─── assistant: "There are 3 TODOs in notes.txt."
```

This is the actual `messages` list at the start of **step 3**, from the run on your machine:

```json
[
  {"role": "user", "content": "How many TODOs are in notes.txt?"},
  {"role": "assistant", "content": "",
   "tool_calls": [{"id": "VAQiyPKSEFgGHvF5CV5Q8Mv3URLnp9y9",
                   "function": {"index": 0, "name": "read_file", "arguments": {"path": "notes.txt"}}}]},
  {"role": "tool", "tool_name": "read_file",
   "content": "TODO: buy milk\nDONE: fix bike\nTODO: email Sam about the project\nTODO: study lesson 03\nDONE: install Ollama\n"}
]
```

Who wrote what:
- `user`: the human.
- `assistant`: the **model**. We send its message back unchanged.
- `tool`: **us**, the harness. The model never sees the file system, only this string.

### 1.5 The rules for sending results back

| Rule | Why |
|---|---|
| **Keep the assistant's `tool_calls` message in the history**, before the results | The result must answer a visible request. Ollama is lenient: we tested it with the request removed and the model still answered. But **OpenAI and Anthropic reject such a history with an error**, and the model loses the record of *why* it has that data. |
| Use `role: "tool"` | marks the text as a tool result, not something the user typed |
| `content` must be a **string** | the model only reads text. Turn numbers, lists and objects into text (or JSON text) first. |
| One result per call, matched to its call | with parallel calls the model must know which result belongs to which request. Ollama matches by `tool_name`; OpenAI and Anthropic by the call's **ID**. |

And remember Lesson 01: the template puts tool results inside a **`user` turn** wrapped in
`<tool_response>`. To the model, a file's contents sit in the same place as instructions from
its user. Hold onto that thought for prompt injection (Lesson 21).

### 1.6 The model decides, so expect four behaviours

Measured on your machine with `qwen3:4b-instruct`:

| You asked | The model did | What your code must handle |
|---|---|---|
| "How many TODOs are in notes.txt?" | **one** call: `read_file` | the basic case |
| "What time is it, and how many TODOs are in notes.txt?" | **two calls in one reply**: `get_current_time` and `read_file` | `tool_calls` is a **list**: loop over it |
| "What is 2 + 2?" | **no** call, answered directly | a reply may have no tool calls; that's the final answer |
| "Read secrets.txt" (doesn't exist) | called `read_file`, got an error, then explained it politely | tools fail; errors must go back to the model |

Several calls in one reply are called **parallel tool calls**. The model asks for everything
it needs at once when the calls don't depend on each other. It saves a whole round trip.

### 1.7 Errors are results, not crashes

When `read_file("secrets.txt")` raised `FileNotFoundError`, the script didn't crash. It sent
the error back as the tool result:

```text
Error: FileNotFoundError: [Errno 2] No such file or directory: 'C:\\Desktop\\Agent Harness\\workspace\\secrets.txt'
```

The model read it and told the user the file doesn't exist. A harness that crashes on a failed
tool kills the whole task; one that reports the error lets the model **recover**: try another
path, list the folder, or ask the user.

But look at that message again. It contains your **full disk path**. Error text goes to the
model, and the model may repeat it to the user. That's a small **information leak**, and
Module 4 will make error messages safer.

### 1.8 Same idea, three dialects

Every major provider supports tool calling, but each formats it differently:

| | Ollama | OpenAI | Anthropic |
|---|---|---|---|
| Tool list | `tools: [{type:"function", function:{name, description, parameters}}]` | same as Ollama | `tools: [{name, description, input_schema}]` |
| Where calls appear | `message.tool_calls[]` | `choices[0].message.tool_calls[]` | content blocks of `type: "tool_use"` |
| Arguments | a JSON **object** | a JSON **string** (you must parse it, and it can be invalid) | a JSON object, called `input` |
| Sending a result | `{role:"tool", tool_name, content}` | `{role:"tool", tool_call_id, content}` | a `user` message containing a `tool_result` block with `tool_use_id` |

Same concepts, different shapes. Lessons 04 and 05 build the layer that hides these
differences from the rest of the harness.

---

## 2. Build

### `scripts/tool_call_by_hand.py`, section by section

**1. The tool definitions (`TOOLS`).** Two tools in Ollama's format: `read_file(path)` and
`get_current_time()`, which takes no arguments, so its `properties` is an empty object `{}`.
This list is all the model will ever know about our functions.

**2. The real functions + a dispatch table.**
```python
def read_file(path):
    # WARNING: no security yet. "../" paths can escape the workspace. Fixed in Lesson 18.
    return (WORKSPACE / path).read_text(encoding="utf-8")

FUNCTIONS = {"read_file": read_file, "get_current_time": get_current_time}
```
`FUNCTIONS` maps the **names the model uses** to the **Python functions we run**. It's
called a *dispatch table*. The model can only trigger functions that are in this dict. An
invented name causes a `KeyError`, not some random code running.

**3. `call_model(messages)`.** One `POST /api/chat` with `"tools": TOOLS`, returning
`["message"]`. Same HTTP code as Lesson 02.

**4. STEP 1.** Send the question. Print the raw reply. **Append the reply to `messages`**
(rule 1). If there are no `tool_calls`, that was the final answer: stop.

**5. STEP 2.** For each call:
```python
name, args = call["function"]["name"], call["function"]["arguments"]
try:
    result = FUNCTIONS[name](**args)
except Exception as e:
    result = f"Error: {type(e).__name__}: {e}"
messages.append({"role": "tool", "tool_name": name, "content": result})
```
`**args` unpacks the dict into keyword arguments: `{"path": "notes.txt"}` becomes
`read_file(path="notes.txt")`. If the model sends a wrong argument name, Python raises
`TypeError`, which becomes an error string for the model, not a crash.

**6. STEP 3.** Send everything back, print the final reply. If it contains *another* tool
call, the script can only say so: it has **no loop**. Handling "the model wants more tools"
is exactly what Lesson 06 adds.

### `workspace/`
A small folder for the agent to explore in this lesson and the next ones: `notes.txt`
(TODOs), `recipes/pancakes.md`, `data/sales.csv`.

---

## 3. Understand: experiments

### Experiment 1: The basic round trip
```bash
.venv\Scripts\python scripts\tool_call_by_hand.py
```
Find: the empty `content` in step 1, the call `id`, and how the step 3 answer uses the file.

### Experiment 2: Parallel calls
```bash
.venv\Scripts\python scripts\tool_call_by_hand.py "What time is it, and how many TODOs are in notes.txt?"
```
Count the entries in `tool_calls`. Why could the model ask for both at once?

### Experiment 3: No tool needed
```bash
.venv\Scripts\python scripts\tool_call_by_hand.py "What is 2 + 2?"
```

### Experiment 4: A failing tool, and a leak
```bash
.venv\Scripts\python scripts\tool_call_by_hand.py "Read secrets.txt and tell me what it says"
```
Read the error string in step 2. What does it reveal about your computer?

### Experiment 5: A tool that doesn't exist
```bash
.venv\Scripts\python scripts\tool_call_by_hand.py "What's the weather in Chennai right now?"
```
There's no weather tool. Does the model admit it can't know, invent an answer, or try to
call a tool that doesn't exist? Run it 2–3 times. Results can vary.

### Experiment 6: Descriptions are prompts
Copy the script, change the `read_file` description to `"Permanently deletes a file."`, and
run Experiment 1 again. Does the model still call it to *read* notes.txt? (Nothing gets
deleted, because the real function only reads. That's the point: **the model only knows
what you tell it**.)

---

## 4. Review

### Quiz
1. Which three messages exist in the history at the start of step 3, and who wrote each?
2. Why must the assistant's tool-call message stay in the history? What did we observe with Ollama when it didn't, and what would OpenAI do?
3. The model returned two tool calls in one reply. What does that mean for your code?
4. A tool raises an exception. Should the harness crash or tell the model? Why?
5. Name two security problems in the script's `read_file`.

### Exercise 1: Add a third tool
Add `count_lines(path)`: it returns how many lines a workspace file has. Write its JSON Schema
in `TOOLS`, the function, and its `FUNCTIONS` entry. Test with *"How many lines does
data/sales.csv have?"*. (Work in a copy of the script so the original stays intact.)

### Exercise 2: Paper trace
For *"What time is it, and how many TODOs are in notes.txt?"*, write the full `messages` list
at the start of step 3, role by role. How many `tool` messages are there?

### Checkpoint
Explain, without notes: who executes a tool, how the model learns the result, and why
errors are sent back to the model instead of crashing.

---

### Answers

<details><summary>Quiz answers</summary>

1. The `user` question (the human), the `assistant` message with `tool_calls` (the model),
   and the `tool` result (the harness).
2. The result has to answer a visible request. Ollama was lenient: the model still answered
   correctly without it. OpenAI rejects the request with an error, and Anthropic too.
   Either way, the model loses the record of what it asked for.
3. `tool_calls` is a list. Run every call and send back one result per call.
4. Tell the model, as a string. It can recover by retrying, trying a different path, or
   explaining the problem. A crash ends the whole task.
5. (a) `../` paths or absolute paths escape the workspace (Lessons 07 and 18). (b) Error
   messages leak full disk paths. (Also: no size limit, so a huge file floods the context.)
</details>

<details><summary>Exercise answers</summary>

**1.**
```python
TOOLS.append({
    "type": "function",
    "function": {
        "name": "count_lines",
        "description": "Count the lines in a text file in the user's workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path relative to the workspace"}},
            "required": ["path"],
        },
    },
})

def count_lines(path):
    return str(len((WORKSPACE / path).read_text(encoding="utf-8").splitlines()))  # results must be strings

FUNCTIONS["count_lines"] = count_lines
```
`data/sales.csv` has **7** lines (1 header + 6 rows).

**2.** `user` → `assistant` (with **two** `tool_calls`) → `tool` (time) → `tool` (notes.txt).
Two `tool` messages, one per call, in the same order as the calls.
</details>

### Glossary
- **Function / tool calling**: a model feature for replying with a structured request to call a named function.
- **JSON Schema**: a standard way to describe the shape of JSON data. Used here to describe tool arguments.
- **Dispatch table**: a dict from names to functions, used to safely route the model's requests.
- **Parallel tool calls**: several tool calls in one model reply.
- **Round trip**: request → tool execution → result → final answer.

**Module 0 complete. Next → Lesson 04: the message model** (Module 1: the agent loop).
