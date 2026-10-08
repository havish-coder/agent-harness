# Commands in the background

A test suite that takes ten minutes shouldn't make the agent (and you) sit and wait. With `background`, a command starts, the agent gets control back at once and goes on with something else, and it is told when the command ends.

```text
● run_shell(command='python -m pytest -q', background=True)
  └ Started background task bg-1: python -m pytest -q
    It runs on while you do other things, and you will be told when it ends. task_output(task='bg-1') shows what it has printed; task_stop(task='bg-1') stops it.
● read_file(path='project/README.md')
  ⏹ background task bg-1 ended: exit code 1 (failure), 42 s  [python -m pytest -q]
● task_output(task='bg-1')
  └ bg-1: exit code 1 (failure), 42 s · python -m pytest -q
    ... FAILED tests/test_cart.py::test_total_with_discount ...
```

## The three pieces
| | |
|---|---|
| `run_shell(command, background=true)` | start it and return at once with an id (`bg-1`, `bg-2`, ...). It is **the same tool** as a normal command, so every rule that applies to commands applies to this one |
| `task_output(task, lines=40, wait=0)` | the end of what it printed, and whether it is still running. `wait` (up to 120 s) waits for it to end first, for when the agent has nothing else to do |
| `task_stop(task)` | stop it, and everything it started. Asks you, like any change |

You can do the same yourself: `/tasks` lists them, `/tasks output bg-1 [LINES]` shows the end of the output, `/tasks stop bg-1` stops one. The status line shows `1 task running`.

## Being told
- **While the agent is working**, a task that ends is reported to it between steps ("background task bg-1 ended: exit code 1"), and shown to you as `⏹ background task ... ended`.
- **While you are thinking**, it is shown when the next prompt appears, and the agent hears about it with your next request.
- Either way **once**. The note says *that* it ended and how (exit code, time), **not what it printed**: what a command prints is text someone else may have written (a failing test can print anything), so it reaches the model only through `task_output`, which is [fenced and tracked as untrusted](untrusted-content.md) like the output of any command.

## Limits and what happens at the end
- **At most four running at once.** Each stops by itself after **30 minutes** (set `timeout` for up to 2 hours).
- Output goes to a **file in your user folder** (`projects/<project>/tasks/`), capped at 2 MB: a command that prints for an hour can't fill the agent's memory. After the cap the command keeps running; what it prints is dropped, and `task_output` says so. With `--no-save` the files are temporary.
- **A task never outlives the session.** When you leave (`/bye`), everything still running is stopped, with its children, and you are told how many.
- The command runs in the same [sandbox](sandbox.md), with the same environment (secrets removed), as a normal one.

## What it measured
TASKS_RESULT

## Setting
`"background_tasks": false` removes the `background` parameter, `task_output` and `task_stop`. A project may set it.
