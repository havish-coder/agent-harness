# Lesson 06 · The Loop

> **Module 1: The Agent Loop** · Condensed lesson. Lesson 03's three manual steps become
> a loop, and the model starts making its own plans.

## Key ideas

**1. The whole thing** (`harness/agent.py`, `Agent.run`):

```python
for _ in range(self.max_steps):                      # stop #2: hard step limit
    reply = self.provider.chat(self.messages, schemas)
    self.messages.append(reply.message)
    if not reply.message.tool_calls:                 # stop #1: final answer
        return reply.message.content
    for call in reply.message.tool_calls:
        result = self.execute(call)                  # the HARNESS acts
        self.messages.append(Message.tool_result(call, result))
return "(stopped: reached the step limit)"
```

That's it. The rest of this course mostly hardens and extends these lines.

**2. Real run on your machine**: *"Find the recipe in my workspace and tell me how many eggs I need."*

```
  -> list_dir(path='.')                  → data/  notes.txt  recipes/
  -> list_dir(path='recipes/')           → pancakes.md
  -> read_file(path='recipes/pancakes.md')
ANSWER: The recipe for pancakes requires 1 egg.          (4 model calls, 1,281 input tokens)
```

Nobody told it to look in `recipes/`. It **planned its own steps** from the tool
results. That's what makes it an agent rather than a chatbot with tools.

**3. Design decisions inside the loop:**

| Decision | Why |
|---|---|
| `max_steps` (default 10) | a confused model can call tools forever. With `max_steps=1` our run stopped after one `list_dir`. |
| `execute()` returns errors as text | unknown tool, bad arguments, missing file: the model sees the error and can recover (Lesson 03) |
| unknown tool → lists the real ones | small models invent tool names; telling them the valid names helps them self-correct |
| **rollback on exception** | if the model errors (or you press Ctrl+C) mid-turn, delete that turn's messages. Otherwise an assistant `tool_calls` message is left without results, and the next request is malformed. |
| `on_event` callback | the loop reports what happens (`tool_call`, `tool_result`, `model_reply`) but doesn't print anything. A CLI, a web UI or a test can each subscribe in its own way. |
| `self.usage` | adds up tokens across all calls, the real cost of a task |
| the tools dict, keyed by name | the model refers to tools by name; lookup is O(1) and unknown names are easy to detect |

**4. A gotcha we hit: history changes behaviour.** After the recipe question, we asked in
the **same conversation** *"What was the total revenue in the sales data?"*. The model made
**no tool calls** and replied *"I don't have access to any sales data"*. A fresh agent asked
the same question explored `data/` and read `sales.csv` every time. Small models are
easily swayed by what's already in context. Better system prompts (Lesson 07) and
context management (Module 5) both help.

## What we built

- `harness/agent.py`: the `Agent` class: `run()`, `execute()`, `reset()`.
- `harness/tools/base.py`: `Tool` = name + description + JSON Schema + Python function.

## Try it

```bash
.venv\Scripts\python -i -c "from harness.agent import Agent; from harness.providers.ollama import OllamaProvider"
```
(`-i` leaves you at a Python prompt with those imported.) Lesson 07 gives you a proper CLI.
For now, read `agent.py` top to bottom. It's about 80 lines and you should be able to explain every one.

## Quiz

1. Name the two stop conditions and what each protects against.
2. Why roll back the turn's messages when an exception happens?
3. The sales answer: the correct total is 2400+1900+2800+2200+3200+1800 = **14,300**. Why is
   it risky to trust a 4B model's arithmetic, and what would a harness give it instead?

<details><summary>Answers</summary>

1. No tool calls in the reply means the final answer (normal finish). `max_steps` reached
   protects against infinite loops: wasted time, tokens and money.
2. A half-finished turn leaves inconsistent history, e.g. tool requests with no results,
   which breaks the next request or confuses the model.
3. Numbers are tokenized digit by digit (Lesson 01), and small models often make addition
   mistakes. Give it a calculator or code-execution tool and let the harness do exact math.
</details>

**Next → Lesson 07: first tools + the REPL.**
