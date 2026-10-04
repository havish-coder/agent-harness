# Lesson 00 · What is an Agent Harness?

> **Module 0: Foundations** · No code yet, this lesson builds the mental model
> that every later lesson hangs on.

## Learning objectives
By the end of this lesson you can:
1. Explain why a raw LLM can't *do* anything on its own.
2. Draw the agent loop from memory.
3. Name the 8 components of a harness and what each one is for.
4. Explain why "the model proposes, the harness disposes" is the key to security.

---

## 1. Learn

### 1.1 The model on its own: text in, text out

Strip away the chat apps and an LLM is just a function:

```
             ┌─────────┐
  text  ───► │   LLM   │ ───►  text
             └─────────┘
```

Three properties of that function matter for everything we build:

| Property | What it means | Consequence |
|---|---|---|
| **Stateless** | Each call starts from zero. The model remembers nothing between calls. | To "remember", *someone* must re-send the whole conversation every time. |
| **Isolated** | It can't read files, open URLs, run code, or check the clock. | Anything it says about the real world is a *guess* unless it's been given the facts. |
| **Probabilistic** | It predicts likely next tokens. It can be confidently wrong. | Its output must be treated as a *proposal*, never as a trusted command. |

### 1.2 Three levels: chatbot → tool use → agent

**Level 1: Chatbot.** Text in, text out. It can explain recursion, but it
can't tell you what's in `notes.txt`.

**Level 2: Tool use (function calling).** We tell the model: *"these functions exist;
if you need one, ask for it in this exact JSON format."* The model can now reply with
a structured request instead of prose:

```json
{ "tool_calls": [ { "function": { "name": "read_file", "arguments": { "path": "notes.txt" } } } ] }
```

The model **did not read the file**. It produced JSON *asking* for it to be read.
Some program has to see that request, actually read the file, and send the
contents back.

**Level 3: Agent.** Put level 2 in a **loop**: the model asks for a tool, gets the
result, decides what to do next (another tool? the final answer?), and repeats until
done. The model now chooses its own *sequence* of steps. A widely used definition:

> **An agent is an LLM using tools in a loop.**

### 1.3 So what is the harness?

The **harness** is all the software around the model that turns level 1 into level 3:
the loop, the tools, the memory, the safety checks, the UI.

The analogy: **the model is the engine, the harness is the rest of the car.**
A great engine on the floor of a garage goes nowhere. The same engine in a car with
bad brakes is dangerous. Claude Code, Codex CLI and Cursor's agent mode are harnesses.
Several of them can run the *same* models; most of what makes them feel different is
the harness.

### 1.4 The agent loop

This is the heart of the whole course. Everything else is a refinement of it.

```
        ┌──────────────────────────────────────────────┐
        │                                              │
        ▼                                              │
  ┌───────────┐    messages[]    ┌─────────┐           │
  │  HARNESS  │ ───────────────► │   LLM   │           │
  │           │ ◄─────────────── │         │           │
  └───────────┘  text or         └─────────┘           │
        │        tool_calls                            │
        ▼                                              │
  tool_calls? ── no ──► show final answer, STOP        │
        │                                              │
       yes                                             │
        ▼                                              │
  allowed by policy? ── no ──► result = "denied" ──────┤
        │                                              │
       yes                                             │
        ▼                                              │
  harness RUNS the tool ──► append result to messages ─┘
```

The same thing in Python-ish pseudocode (you'll write the real version in Lesson 06):

```python
messages = [system_prompt, user_message]
for step in range(MAX_STEPS):                  # safety: never loop forever
    reply = llm.chat(messages, tools=tool_schemas)
    messages.append(reply)
    if not reply.tool_calls:                   # model is done → final answer
        return reply.content
    for call in reply.tool_calls:
        if policy.allows(call):
            result = tools[call.name](**call.arguments)
        else:
            result = "Error: permission denied"
        messages.append({"role": "tool", "content": result})
```

### 1.5 A worked example: watching the `messages` list grow

User asks: *"How many TODOs are in notes.txt?"*

**Model call #1.** The harness sends:
```text
[system]    You are a helpful agent. You can use tools: read_file(path), list_dir(path)
[user]      How many TODOs are in notes.txt?
```
The model replies with **no text, just a tool request**:
```text
[assistant] tool_calls: read_file(path="notes.txt")
```

**The harness acts.** It checks the policy (reading inside the workspace: allowed),
opens the real file, and appends the result:
```text
[tool]      TODO: buy milk\nDONE: fix bike\nTODO: email Sam\nTODO: study lesson 01
```

**Model call #2.** The harness sends the **entire list again** (remember: stateless):
```text
[system]    You are a helpful agent...
[user]      How many TODOs are in notes.txt?
[assistant] tool_calls: read_file(path="notes.txt")
[tool]      TODO: buy milk\nDONE: fix bike\nTODO: email Sam\nTODO: study lesson 01
```
The model now has the facts and replies with plain text:
```text
[assistant] There are 3 TODOs in notes.txt.
```
No tool calls → loop ends → the CLI prints the answer.

Notice:
- **Two model calls** happened for one user question. Agents are chatty, and every call re-sends
  the growing history. This is why context management (Module 5) matters.
- The answer is **grounded**: it came from the real file, not from the model's imagination.

### 1.6 Anatomy of a harness: the 8 components

```
            ┌──────────────────────────── HARNESS ────────────────────────────┐
  User ───► │ ① Interface (CLI / Web UI)                                      │
            │        │                                                        │
            │        ▼                                                        │
            │ ② Context manager: builds messages[] from system prompt,        │
            │        │            memory, history, tool results               │
            │        ▼                                                        │
            │ ③ Provider adapter ───────────────────────►  LLM               │
            │        │           ◄──── text or tool_calls ── (Ollama / API)   │
            │        ▼                                                        │
            │ ④ Agent loop ── tool call? ──► ⑤ Permission policy             │
            │        ▲                          │ allow / ask user / deny     │
            │        │                          ▼                             │
            │        └──── result ◄──── ⑥ Tool system ──► sandboxed actions  │
            │                                                                 │
            │ ⑦ Memory & sessions (persist across runs)                       │
            │ ⑧ Trace / audit log (records every step)                        │
            └─────────────────────────────────────────────────────────────────┘
```

| # | Component | Job | We build it in |
|---|---|---|---|
| ① | **Interface** | Takes user input, streams output, shows tool calls, asks for approvals | Lessons 07, 12, Module 6 |
| ② | **Context manager** | Decides *what goes into* `messages[]`, keeps it under the context-window limit | Module 5 |
| ③ | **Provider adapter** | Translates between our internal format and each vendor's API format | Lessons 05, 14 |
| ④ | **Agent loop** | Runs the cycle; stop conditions; step limits | Lesson 06 |
| ⑤ | **Permission policy** | Decides if a requested action may run: allow / ask / deny | Lesson 19 |
| ⑥ | **Tool system** | Defines tools (schemas), validates arguments, executes, trims huge outputs | Module 2 |
| ⑦ | **Memory & sessions** | Saves conversations; loads project instructions | Lessons 28-29 |
| ⑧ | **Trace / audit** | A log of every model call, tool call and decision, for debugging and security | Lesson 24 |

### 1.7 The key insight: *the model proposes, the harness disposes*

The model **never touches your computer**. It can only *ask*. Every file read,
command, or web request is performed by harness code that **you** wrote. Two consequences:

1. **Security lives in the harness.** You can't make a model 100% obedient. Text it reads
   can trick it (that's *prompt injection*, Lesson 21). But you *can* make the harness
   refuse to run `delete everything` no matter what the model asks. Defense goes in the
   code path between "model asked" and "action happened".
2. **Treat model output like user input from a stranger.** Tool arguments come from a
   probabilistic text generator that may have read malicious content. Validate them
   like you'd validate a web form.

### 1.8 How production harnesses map to this

| Component | Claude Code (what you're using right now) | Ours |
|---|---|---|
| Loop | Model → tools → results → model... | `harness/agent.py` |
| Tools | `Read`, `Write`, `Edit`, `Bash`, `Grep`, `Glob`, web fetch... | `harness/tools/` |
| Permissions | Permission modes, allow/deny rules, approval prompts, plan mode | `harness/policy.py` |
| Context | Automatic compaction of long conversations | `harness/context.py` |
| Memory | `CLAUDE.md` instruction files, memory directory | `AGENT.md` loader |
| Extensibility | MCP servers, hooks, sub-agents | Capstone |

---

## 2. Build

Nothing to code yet. This lesson created the course skeleton:

```
course/
  README.md                         ← syllabus with progress checkboxes
  00-what-is-an-agent-harness.md    ← this file
```

and initialised the git repository with the tag `lesson-00`.

---

## 3. Understand: experiments

### Experiment 1: You've already watched a harness work
Scroll back through **this Claude Code conversation**. Find an example of each, and
match it to a component number from the anatomy diagram:

- a **tool call** (e.g. checking which Python version you have) → ?
- a **human approval moment**. Hint: when you *rejected* my first plan and asked for
  a course instead, which component was that? → ?
- **memory** written to disk so the next session remembers this project → ?

<details><summary>Answers</summary>

- Tool call → ⑥ tool system, run by ④ the loop.
- Rejecting the plan → ⑤ permission policy (human-in-the-loop). The model *proposed*
  a plan; the harness made it wait for *your* decision. That's "the model proposes,
  the harness disposes" in action.
- Memory files → ⑦ memory.
</details>

### Experiment 2: Prove the model is stateless
Run these two **separate** commands in a terminal:

```bash
ollama run qwen2.5:0.5b "Remember this: my favourite colour is teal."
```

```bash
ollama run qwen2.5:0.5b "What is my favourite colour?"
```

It won't know. Each command is a fresh call with no history.
(The first run can take a while because Ollama is loading the model into memory.
Later runs are fast.)

Now run `ollama run qwen2.5:0.5b` with **no prompt** (interactive mode), say the
colour, then ask about it. Now it remembers! Why? The interactive REPL is a tiny
harness that re-sends the conversation history every turn. (Type `/bye` to exit.)

### Experiment 3: A model without tools can't see reality
```bash
ollama run qwen2.5:0.5b "How many files are in the folder C:\Desktop\Agent Harness right now?"
```
Watch it guess, make something up, or admit it can't know. The model isn't broken.
It has no tools. By Lesson 07 our agent will answer this correctly by calling `list_dir`.

---

## 4. Review

### Quiz
1. LLM calls are stateless. So how does a chat app "remember" what you said earlier?
2. When a model "calls a tool", who actually executes it? Why does that matter for security?
3. What is the stop condition of the basic agent loop? What *second* stop condition
   should every real loop have, and why?
4. Which component handles each job?
   (a) converting Ollama's JSON into our internal format,
   (b) deciding whether `delete_file` may run,
   (c) keeping the conversation under the model's context limit.
5. Why can the *same* model seem brilliant in one product and useless in another?

### Exercise (optional, pen and paper)
User asks: *"Read draft.txt, then rename it to final.txt."*
Tools available: `read_file(path)` and `rename_file(src, dst)`.
Write out the full `messages` list, role by role, from the first user message to the
final answer. How many model calls happen? Could it be fewer?

### Checkpoint
Without looking at your notes, explain to yourself (or to me) in three sentences:
**what a harness is, what the loop does, and why the model never directly acts.**
When you can, you're ready for Lesson 01.

---

### Quiz answers

<details><summary>Click to reveal</summary>

1. The app (a harness) **re-sends the whole conversation** on every call. The "memory"
   lives in the harness, not the model.
2. **The harness** executes it; the model only emits a JSON request. That means every
   action passes through code we control, so we can validate, restrict, ask the human, or
   refuse. Security is enforced *there*.
3. Stop when the model replies **without any tool calls** (it's giving the final answer).
   Also stop at a **maximum step count**, because a confused model can loop forever
   (calling the same tool repeatedly), burning time and money.
4. (a) ③ provider adapter · (b) ⑤ permission policy · (c) ② context manager.
5. The harness decides which tools the model has, what context it sees, how errors are
   fed back, and how results are formatted. Good tools and context make a model look smart;
   missing or confusing ones make it look dumb.

**Exercise:** typically 3 model calls: (1) model → `read_file`, (2) model → `rename_file`,
(3) model → final answer. It *could* be 2 if the model requests both tools in one reply
(parallel tool calls), since both only depend on the original request.
</details>

---

### Glossary
- **Token**: a chunk of text (roughly ¾ of a word) that models read and write.
- **Context window**: the maximum number of tokens a model can consider in one call.
- **System prompt**: instructions at the start of `messages[]` that set the model's role and rules.
- **Tool / function calling**: a model feature for emitting structured requests to call named functions.
- **Tool schema**: a JSON description of a tool's name, purpose and parameters, sent to the model.
- **Provider**: a service that runs a model (Ollama locally, or a cloud API).
- **Harness**: everything around the model that makes it an agent.

**Next → Lesson 01: LLMs as an API** (tokens, context windows, roles, sampling, plus
setting up Python, git, and the `qwen3:4b` model).
