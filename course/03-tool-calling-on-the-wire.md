# Lesson 03 · Tool Calling on the Wire

> **Module 0: Foundations** · Condensed lesson. One complete tool-calling round trip, by
> hand, with every message printed. This is the last piece before we build the loop.

## Key ideas

**1. A tool is described with JSON Schema.** The model never sees your Python code, only
this description. **The description is a prompt**: it's how the model decides *when* and
*how* to use the tool.

```json
{ "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read a text file from the user's workspace and return its contents.",
    "parameters": {
      "type": "object",
      "properties": { "path": {"type": "string", "description": "File path relative to the workspace"} },
      "required": ["path"] } } }
```

**2. The round trip has three steps:**

```
 STEP 1  harness ──[ user msg + tools ]──► model ──► assistant msg with tool_calls (no text)
 STEP 2  harness runs the function itself  ──► result string
 STEP 3  harness ──[ history + assistant msg + tool result ]──► model ──► final answer
```

Real tool call from your machine:
```json
{ "role": "assistant", "content": "",
  "tool_calls": [{ "id": "VAQiyPKSEFgGHvF5CV5Q8Mv3URLnp9y9",
                   "function": {"name": "read_file", "arguments": {"path": "notes.txt"}} }] }
```

**3. Sending the result back has two rules:**
- The **assistant message with the `tool_calls` must stay in the history**. Otherwise the
  model sees a tool result for a request it never made.
- The result is a `tool` message, and its content must be a **string**:
  `{"role": "tool", "tool_name": "read_file", "content": "TODO: buy milk\n..."}`

**4. The model chooses what to do.** It's a decision, not a command:

| Asked | What `qwen3:4b-instruct` did |
|---|---|
| "How many TODOs are in notes.txt?" | 1 call: `read_file` |
| "What time is it, and how many TODOs...?" | **2 calls in one reply** (parallel): `get_current_time` + `read_file` |
| "What is 2 + 2?" | no tool, answered directly |
| "Read secrets.txt" (doesn't exist) | called `read_file`, got an error string, and told the user politely |

**5. Errors are results, not crashes.** When the tool fails, we send the error text back
to the model, and it adapts. A harness that crashes on a bad tool call is fragile; one that
reports errors lets the model fix its own mistakes.

**6. Vendor differences start here.** Ollama gives `arguments` as a JSON **object**.
OpenAI-style APIs give it as a JSON **string** you must parse, which can be invalid JSON.
Another job for the adapter (Lesson 05).

## What we built

- **`scripts/tool_call_by_hand.py`**: two tools (`read_file`, `get_current_time`), the
  three steps, each printed. It has **no loop**: if the model asks for another tool in
  step 3, the script can only point that out. That limitation is exactly why Lesson 06 exists.
- **`workspace/`**: a sandbox folder for the agent: `notes.txt`, `recipes/pancakes.md`,
  `data/sales.csv`.

## Try it

```bash
.venv\Scripts\python scripts\tool_call_by_hand.py
```
```bash
.venv\Scripts\python scripts\tool_call_by_hand.py "What time is it, and how many TODOs are in notes.txt?"
```
```bash
.venv\Scripts\python scripts\tool_call_by_hand.py "Read secrets.txt and tell me what it says"
```

Things to notice:
1. In step 1 the model's `content` is **empty**. It only emitted a tool call.
2. In the `secrets.txt` run, the error string contains your **full disk path**
   (`C:\Desktop\Agent Harness\workspace\...`). Tool output goes to the model and could be
   repeated to the user. That's a small **information leak**. Remember it for Module 4.
3. Look at `read_file`: nothing stops `path="../../somewhere/else"`. The model could read
   **any file on your computer**. Lesson 18 adds the sandbox.
4. Try editing a tool's `description` in the script to something misleading (e.g.
   "Deletes a file") and re-run. Does the model still use it?

## Quiz

1. Why must the assistant's tool-call message be appended to the history before the tool result?
2. A tool raises an exception. Should the harness crash, or tell the model? Why?
3. What did the model do when asked two questions that each needed a different tool?

<details><summary>Answers</summary>

1. The model needs to see that *it* requested the call. Without it, the tool result has no
   matching request and the conversation is inconsistent. Many APIs reject it outright.
2. Tell the model, as a result string. It can then retry with a different argument, try
   another approach, or explain the problem to the user. Crashing kills the whole task.
3. It requested both tools in **one** reply (parallel tool calls), so the harness must
   handle a *list* of calls, not just one.
</details>

**Module 0 complete. Next → Module 1: the agent loop.**
