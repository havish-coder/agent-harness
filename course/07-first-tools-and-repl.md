# Lesson 07 · First Tools + the REPL

> **Module 1: The Agent Loop** · Condensed lesson. Real file tools, a terminal app, and
> what happened when the first version misbehaved: a sandbox escape and a prompt that
> turned tool use off.

## Key ideas

**1. Tools bound to a workspace.** `make_fs_tools(workspace)` returns `list_dir` and
`read_file` as closures over one folder, so each agent gets tools for *its* workspace.
Tool results are plain text the model can read: `notes.txt  (107 bytes)`, folders end in `/`.

**2. The REPL is a thin shell around `Agent`.** `harness/cli.py` reads input, calls
`agent.run()`, and subscribes to `on_event` to print tool activity live:

```
you> What was the total revenue in the sales data?
  → read_file(path='data/sales.csv')
    month,region,units,revenue ...
agent> Sum = 2400 + 1900 + 2800 + 2200 + 3200 + 1800 = 14,300
  [1007 input + 196 output tokens]
```

Commands: `/reset` forgets the conversation, `/bye` quits, and **Ctrl+C** cancels a running
task (the loop rolls back that turn, as in Lesson 06).

**3. 🔓 We escaped the sandbox by accident.** In the first test run, *"What files are in this
folder?"* made the model call `list_dir(path='/')`. In Python's `pathlib`, joining an
absolute path **replaces** the base:

```python
Path("C:/Desktop/Agent Harness/workspace") / "/"   →   C:/            # the whole drive!
```

The agent listed the top of the C: drive, including personal folder names, without anyone
attacking anything. It was an innocent question and an innocent model. It's read-only and
stayed on your machine, but this is exactly the vulnerability Module 4 is about. **Keep it
in mind:** until Lesson 18, these tools can read anything on your disk.

**4. 🧪 The prompt that switched tools off.** The first system prompt said *"Whenever an answer
depends on files, use the tools."* The model kept answering *"I don't have access to any
sales data"*, or invented a file name, `sales_data.txt does not exist`, without calling a
single tool. We measured instead of guessing:

| System prompt | Tool descriptions | Tool used |
|---|---|---|
| "Whenever an answer **depends on files**, use the tools..." (long, bullet list) | either | **0/8** |
| "Use tools to inspect the workspace; never guess file contents." | `fs.py` | 4/4 |
| reworded, more detail | `fs.py` | 2-4 / 6 |
| short prompt **+ snapshot of the workspace files** | `fs.py` | **12/12** (fresh and follow-up) |

What we learned:
- **Conditional instructions give the model an escape hatch.** "Use tools *when* X" lets the
  model decide X doesn't apply. It didn't know the sales data was a file.
- **Small models need short, direct prompts.** More rules ≠ better behaviour.
- **Tell the model what's in its environment.** With a file tree in the system prompt, the
  model *knows* `data/sales.csv` exists and goes straight to it. That's also cheaper:
  726 input tokens instead of 1,264 for the TODO question. Real harnesses do the same
  (Claude Code tells the model its working directory, platform, git status...).
- **Measure prompt changes.** Run each variant several times. One success proves nothing
  with a probabilistic model.

The snapshot is labelled *"may have changed since"* because it's taken once at startup.
That's why the agent still has `list_dir` for the live view.

## What we built

| File | What |
|---|---|
| `harness/tools/fs.py` | `make_fs_tools()` (`list_dir`, `read_file`) and `workspace_snapshot()` (a tree capped at 50 entries) |
| `harness/cli.py` | the REPL: live tool display, token usage per turn, `/reset`, `/bye`, Ctrl+C |
| `pyproject.toml` | a `harness` command, installed into the venv |

## Try it

```bash
.venv\Scripts\harness
```

Ask:
1. `How many TODOs are in notes.txt?`
2. `What was the total revenue in the sales data?` (check: 14,300)
3. `How many eggs do I need for the pancakes?`
4. `Which month had the most units sold?`, which needs reading *and* reasoning.

Then experiment:
- Edit `SYSTEM_PROMPT` in `harness/cli.py` back to a conditional "use tools whenever..."
  version and watch tool use drop.
- Run with the thinking model: `.venv\Scripts\harness --model qwen3:4b`. Is it more
  reliable? How much slower?
- Point it at another folder: `.venv\Scripts\harness --workspace C:\path\to\some\folder`
  (read-only tools, but remember point 3).

## Quiz

1. Why is `list_dir` built as a closure inside `make_fs_tools(workspace)` instead of a plain module-level function?
2. Why did "use tools whenever an answer depends on files" fail?
3. What are the trade-offs of putting a workspace snapshot in the system prompt?

<details><summary>Answers</summary>

1. The tool needs to know *which* folder it serves without the model passing it in. A closure
   binds it once, and the model only ever sees relative paths. (Lesson 08 shows another way.)
2. It made tool use conditional, and the model judged the condition false: it didn't know
   "sales data" meant a file in the workspace. Direct instructions plus environment facts
   remove the guesswork.
3. **Pros:** the model knows what exists, makes fewer calls, and skips exploration. **Cons:**
   it costs tokens on every call (so cap its size), it goes stale when files change, and it
   reveals file names to the model. That's fine here, but it matters if names are sensitive.
</details>

**Module 1 complete.** You now have a working agent: a provider adapter, a loop, tools,
and a REPL, in about 300 lines of your own code.
**Next → Module 2: the tool system** (`@tool` decorator, registry and validation, file
editing, shell, streaming, testing).
