# Lesson 07 · First Tools + the REPL

> **Module 1: The Agent Loop** · Real file tools, a terminal app you can chat with, and
> the story of what went wrong in the first test: a sandbox escape nobody asked for, and a
> system prompt that switched tool use off.

## Learning objectives
By the end of this lesson you can:
1. Design tool output that a model reads easily.
2. Bind tools to a workspace using closures, and name the alternatives.
3. Explain how the REPL is put together, including the Windows terminal details.
4. Explain exactly how `list_dir('/')` escaped the workspace.
5. Run a measured prompt experiment, and explain why putting the environment into the system
   prompt fixed tool use.

---

## 1. Learn

### 1.1 Designing tool output for a model

The model reads a tool's output once, as plain text, and has to act on it. Design that text
the way you'd design a UI:

```text
data/
recipes/
notes.txt  (107 bytes)
```

| Choice in `list_dir` | Why |
|---|---|
| folders end with `/` | the model can tell folders from files without another call |
| folders first, then files, alphabetical | stable and predictable output |
| file sizes | lets the model avoid reading a huge file it doesn't need |
| `(empty folder)` instead of `""` | an empty string looks like the tool failed or returned nothing useful |
| one entry per line, no decoration | fewer tokens, easy to scan |

Good tool output is **compact, consistent and unambiguous**.

### 1.2 Binding tools to a workspace

`list_dir` needs to know *which* folder is the workspace, but the model should never pass
that in, because it only works with relative paths. We bind it with a **closure**:

```python
def make_fs_tools(workspace: Path) -> list[Tool]:
    def list_dir(path: str = ".") -> str:
        target = workspace / path        # `workspace` is captured from the outer function
        ...
    return [Tool("list_dir", ..., fn=list_dir), ...]
```

Each call to `make_fs_tools()` creates fresh functions that remember their own `workspace`.
Two agents with two workspaces get two independent sets of tools.

| Way to bind state to a tool | Looks like | Notes |
|---|---|---|
| **closure** (what we use) | inner function captures `workspace` | simple, no classes |
| class with methods | `FsTools(workspace).list_dir` | good when tools share a lot of state |
| `functools.partial` | `partial(list_dir, workspace)` | but then `workspace` leaks into the schema unless you're careful |
| context object passed in | `list_dir(ctx, path)` | what Lesson 08's `@tool` decorator will use |

### 1.3 The REPL

```
main()
 ├─ parse arguments (--model, --workspace, --max-steps)
 ├─ terminal setup (colours, UTF-8)
 ├─ build the system prompt (with a snapshot of the workspace)
 ├─ create Agent(provider, tools, prompt, on_event=show_event)
 └─ loop:
      input "you>"  ──► /bye → quit     /reset → agent.reset()
                    ──► agent.run(text)
                          │  events → show_event() prints  → read_file(path='notes.txt')
                          ▼
                    print "agent> answer"  +  [input + output tokens for this turn]
```

`cli.py` contains **no agent logic**. It's input, output and display. All the intelligence is
in `Agent`. That's why Module 6 can put a web UI on the same `Agent` without touching the loop.

### 1.4 Terminal details

| Detail | Why it's there |
|---|---|
| `"\033[36m"` etc. | **ANSI escape codes**: the terminal reads them as "switch colour". `\033[0m` resets. |
| `os.system("")` on Windows | a well-known trick: it makes older Windows consoles start interpreting ANSI codes |
| `sys.stdout.reconfigure(encoding="utf-8")` | Windows terminals default to cp1252 and crash on `→`, `…` or non-English text (Lesson 01) |
| Ctrl+C **at the prompt** | `KeyboardInterrupt` from `input()`, which quits the app |
| Ctrl+C **while the agent works** | `KeyboardInterrupt` from `agent.run()`. The loop rolls back (Lesson 06) and the CLI prints `(cancelled)` and keeps going. |
| token line after each answer | the CLI subtracts `agent.usage` before and after `run()` to show the cost of this turn alone |

`pyproject.toml` declares a **console script**:
```toml
[project.scripts]
harness = "harness.cli:main"
```
`pip install -e .` then created `.venv\Scripts\harness.exe`, which calls `harness.cli.main()`.

### 1.5 🔓 How `list_dir('/')` escaped the workspace

In the first test run, *"What files are in this folder?"* made the model call
`list_dir(path='/')`, and the agent listed the **top of your C: drive**. Nobody was attacking
anything. It was an innocent question and an innocent model.

The cause is how `pathlib`'s `/` operator works: **if the right-hand side is an absolute
path, it replaces the left-hand side entirely**. Measured on your machine (pure path
arithmetic, no files touched):

| Model passes `path=` | `workspace / path` becomes | Inside the workspace? |
|---|---|---|
| `notes.txt` | `...\workspace\notes.txt` | ✅ |
| `''` or `.` | `...\workspace` | ✅ |
| `../secret.txt` | `...\workspace\..\secret.txt` → resolves to `C:\Desktop\Agent Harness\secret.txt` | ❌ one level up |
| `/` | `C:\` | ❌ **drive root** |
| `/notes.txt` | `C:\notes.txt` | ❌ |
| `C:/Windows` | `C:\Windows` | ❌ |
| `D:/x` | `D:\x` | ❌ another drive |

To the model, `/` *means* "the root of the workspace", and that's a reasonable guess. Our
code turned it into "the root of the disk". It was read-only and the output only went to your
local model, but with a cloud model, that listing would have been sent over the internet. The
fix (Lesson 18) is to resolve the full path and **check it's still inside the workspace**:

```python
target = (workspace / path).resolve()
if not target.is_relative_to(workspace):   # Python 3.9+
    raise PermissionError("path is outside the workspace")
```

Until then, **these tools can read anything on your disk.**

### 1.6 🧪 The prompt that switched tool use off

The first `SYSTEM_PROMPT` was careful and detailed:

```text
You are a helpful assistant running inside an agent harness.
You can use tools to look at files in the user's workspace folder.
- Whenever an answer depends on files, use the tools. Never guess what a file contains.
- Check again with tools even if you looked earlier: files may have changed.
- All paths are relative to the workspace root.
- Be concise.
```

In testing, *"What was the total revenue in the sales data?"* got *"I don't have access to
any sales data"*, or worse, *"The file `sales_data.txt` does not exist"* (an invented
file name), without a single tool call. So we **measured**, asking the question several
times per variant:

| System prompt | Tool descriptions | Called a tool |
|---|---|---|
| detailed prompt above ("**whenever** an answer depends on files...") | old or `fs.py` | **0 / 8** |
| lower temperature (0.2), same prompt | `fs.py` | 0 / 3 (temperature isn't the cause) |
| "Use tools to inspect the workspace; never guess file contents." | `fs.py` | 4 / 4 |
| reworded with more guidance | `fs.py` | 2–4 / 6 |
| **short prompt + snapshot of the workspace files** | `fs.py` | **12 / 12**, fresh and follow-up |

What we learned:
1. **Conditional instructions give the model a way out.** "Use tools *whenever* X" lets the
   model decide X doesn't apply. It didn't know "sales data" was a file.
2. **For small models, short and direct beats long and careful.** More rules ≠ better behaviour.
3. **Tell the model what exists.** With the file tree in the prompt, the model *knows*
   `data/sales.csv` is there and reads it directly.
4. **Measure, don't guess.** One success proves nothing with a probabilistic model. Run each
   variant several times, and change one thing at a time (prompt, then tools, then temperature).

### 1.7 Putting the environment into the system prompt

The final prompt:

```text
You are a helpful agent. Use tools to inspect the workspace; never guess file contents.
Explore folders with list_dir before saying something doesn't exist.
Paths are relative to the workspace root. Be concise.

Workspace files (snapshot at session start; may have changed since):
data/
  sales.csv
recipes/
  pancakes.md
notes.txt
```

Real harnesses do this all the time: Claude Code's system prompt includes facts like the
working directory, platform and date. The trade-offs:

| ✅ Pros | ⚠️ Cons |
|---|---|
| the model knows where things are, so fewer exploratory calls | costs tokens on **every** call, which is why it's capped at 50 entries |
| cheaper overall: the TODO question used 726 input tokens instead of 1,264 | it goes **stale**: the label "may have changed since" tells the model to verify |
| more reliable tool use (12/12) | it reveals file names to the model, so be careful if names are sensitive |

---

## 2. Build

### `harness/tools/fs.py`

**`workspace_snapshot(workspace, depth=2, limit=50)`**: walks the folder recursively with an
inner `walk()` function, folders first, indenting two spaces per level, and stops at 50 lines,
adding `... (more files not shown; use list_dir)`. Depth 2 means top level plus one level
inside.

**`make_fs_tools(workspace)`**: returns two `Tool`s bound by closure:
- `list_dir(path=".")`: entries sorted with `key=(p.is_file(), p.name.lower())`. `False`
  sorts before `True`, so folders come first. Sizes come from `p.stat().st_size`.
- `read_file(path)`: `read_text(encoding="utf-8")`. Always pass the encoding on Windows,
  where the default isn't UTF-8.

`PATH_PARAM` is one shared schema snippet for the `path` argument, with an example value in its
description: `"e.g. notes.txt or recipes/"`. Example values noticeably help small models.

### `harness/cli.py`

- `SYSTEM_PROMPT` has a `{snapshot}` placeholder, filled in by `.format()` at startup.
- `show_event()` prints `tool_call` events in cyan and `tool_result` events dimmed, cutting
  results longer than 300 characters to a preview.
- `main()`: arguments → terminal setup → resolve the workspace and check it exists → build
  the agent → the input loop (section 1.3), with `ProviderError` caught per turn so one failed
  call doesn't end the session.

---

## 3. Understand: experiments

### Experiment 1: Use your agent
```bash
.venv\Scripts\harness
```
Ask these and check the answers:

| Question | Correct answer |
|---|---|
| How many TODOs are in notes.txt? | 3 |
| What was the total revenue in the sales data? | 14,300 |
| How many eggs do I need for the pancakes? | 1 |
| Which month had the most units sold? | **a tie**: August and September, 250 units each |

The last one is a trap: it needs reading, adding up per month, *and* noticing a tie. Did your
agent get it?

### Experiment 2: The path escape, safely
Pure path arithmetic, no files are read:
```bash
.venv\Scripts\python -c "from pathlib import Path; ws = Path(r'C:\Desktop\Agent Harness\workspace'); [print(repr(p), '->', (ws / p).resolve()) for p in ['notes.txt', '../secret.txt', '/', 'C:/Windows']]"
```

### Experiment 3: Break the prompt, and measure it
Paste into `.venv\Scripts\python`:
```python
from pathlib import Path
from harness.agent import Agent
from harness.providers.ollama import OllamaProvider
from harness.tools.fs import make_fs_tools, workspace_snapshot
from harness.cli import SYSTEM_PROMPT

ws = Path("workspace").resolve()
GOOD = SYSTEM_PROMPT.format(snapshot=workspace_snapshot(ws))
BAD = "You are a helpful assistant. Whenever an answer depends on files, use the tools."

def tool_use_rate(prompt, question, runs=4):
    used = 0
    for _ in range(runs):
        calls = []
        agent = Agent(OllamaProvider(), make_fs_tools(ws), prompt,
                      on_event=lambda kind, data: calls.append(data) if kind == "tool_call" else None)
        agent.run(question)
        used += bool(calls)
    return f"{used}/{runs}"

q = "What was the total revenue in the sales data?"
print("GOOD:", tool_use_rate(GOOD, q))
print("BAD: ", tool_use_rate(BAD, q))
```
This is a tiny **evaluation**: run a fixed question several times and count a measurable
behaviour. The capstone module builds a proper eval set this way.

### Experiment 4: The thinking model as the agent
```bash
.venv\Scripts\harness --model qwen3:4b
```
Ask the "most units sold" question. Is it more accurate? How much slower?

### Experiment 5: Another folder
```bash
.venv\Scripts\harness --workspace C:\path\to\a\folder\you\choose
```
The tools are read-only, but remember section 1.5: until Lesson 18, the agent can read *outside*
that folder too. Don't point it near anything private.

---

## 4. Review

### Quiz
1. Why does `list_dir` return `(empty folder)` instead of an empty string?
2. Why is `list_dir` defined inside `make_fs_tools()` instead of at module level?
3. Why did `workspace / "/"` produce `C:\`?
4. Why did "use the tools *whenever* an answer depends on files" fail?
5. Give one advantage and two disadvantages of putting a workspace snapshot in the system prompt.
6. In Experiment 3, why run each prompt several times instead of once?

### Exercise 1: A `/history` command
Add `/history` to the CLI: print each message's role and the first 60 characters of its
content (or its tool calls). Use it to watch the history grow during a task.

### Exercise 2: A `count_lines` tool
Add a third tool to `make_fs_tools()` that returns the number of lines in a file. Ask
*"How many rows of sales data are there?"* Does the model subtract the header line?

### Exercise 3: Your own eval
Extend Experiment 3 to run all four questions from Experiment 1 and check the answers
automatically (e.g. `"14,300" in answer or "14300" in answer`). Print a score.

### Checkpoint
You can start `harness`, explain every line of output, and explain why the system prompt looks
the way it does.

---

### Answers

<details><summary>Quiz answers</summary>

1. An empty string is ambiguous: the model might think the tool failed or returned nothing. An
   explicit message is unambiguous.
2. So it can capture `workspace` without the model passing it in. Each `make_fs_tools()` call
   produces tools bound to their own folder.
3. In `pathlib`, joining an absolute path **replaces** the base path. `/` is absolute (the root
   of the current drive), so the workspace part is thrown away.
4. The condition gave the model a way out: it judged that the question didn't depend on files,
   because it didn't know the sales data *was* a file.
5. **Advantage:** the model knows what exists, which means fewer calls, lower cost and more
   reliable tool use. **Disadvantages:** costs tokens on every call; goes stale when files
   change; exposes file names to the model.
6. The model is probabilistic: one run can succeed or fail by chance. Several runs give a
   success *rate* you can compare between variants.
</details>

<details><summary>Exercise answers</summary>

**1.** In the CLI loop:
```python
if user == "/history":
    for m in agent.messages:
        if m.tool_calls:
            text = ", ".join(f"{c.name}({c.arguments})" for c in m.tool_calls)
        else:
            text = m.content.replace("\n", " ")
        print(f"{DIM}  {m.role:9} {text[:60]}{RESET}")
    continue
```

**2.** In `make_fs_tools()`:
```python
def count_lines(path: str) -> str:
    return str(len((workspace / path).read_text(encoding="utf-8").splitlines()))
```
plus a `Tool("count_lines", "Count the lines in a text file in the workspace.",
{"type": "object", "properties": {"path": PATH_PARAM}, "required": ["path"]}, count_lines)`
in the returned list. `sales.csv` has 7 lines: 1 header + 6 data rows.

**3.**
```python
checks = {
    "How many TODOs are in notes.txt?": ["3"],
    "What was the total revenue in the sales data?": ["14,300", "14300"],
    "How many eggs do I need for the pancakes?": ["1"],
}
score = 0
for q, ok in checks.items():
    answer = Agent(OllamaProvider(), make_fs_tools(ws), GOOD).run(q)
    passed = any(s in answer for s in ok)
    score += passed
    print("PASS" if passed else "FAIL", q)
print(f"score: {score}/{len(checks)}")
```
(Checking `"1"` for eggs is weak, since any answer containing a 1 passes. Real evals need
careful checks, often a second model as a judge. More in the capstone.)
</details>

### Glossary
- **Closure**: an inner function that remembers variables from the function that created it.
- **ANSI escape code**: a special character sequence a terminal reads as a command (colour, bold...).
- **Console script**: a command that `pip` installs and that runs a Python function.
- **Path traversal**: escaping an intended folder using `../` or absolute paths.
- **Environment context**: facts about the agent's surroundings put into the system prompt.
- **Eval (evaluation)**: running fixed tasks repeatedly to measure a model or prompt's behaviour.

**Module 1 complete.** In about 300 lines of your own code you have a provider adapter, a loop,
tools, and a terminal app.
**Next → Module 2: the tool system** (`@tool` decorator, registry and validation, file editing,
shell, streaming, testing).
