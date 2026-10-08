# 0046. Run a command in the background with a parameter of `run_shell`, not with a second tool

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
`run_shell` blocks. A ten-minute test run holds up the agent, the user, and (on a small local model) a model that has nothing to do while it waits. Running a command in the background is a small feature
with one large trap: **every rule that decides whether a command may run is about `run_shell`**: deny and ask rules written as `run_shell(rm *)`, the command analysis that finds `curl | sh`, hooks that match the
tool's name, the sandbox, the approval question. A second tool for background commands would be a way round every one of them: the same `rm -rf` as `run_background`.

Measured (`scripts/tasks_lab.py latency`): a command that takes 3 s blocks for 3.4 s; starting it in the background returned in **28 ms**. And, in the same lab, what a 4B model does with the choice: told to run it in the background, the model did (4 of 4) and then **never came back for the output** (0 of 4 waited or read it): it reported the TODO count, promised the build ("I will now wait for the background task to complete"), and ended its turn. Not told, it ran the command normally (0 of 4 in the background) and reported both results. The user hears when the task ends, and the model with the next request; nothing is lost, but nothing makes the model wait either.

| asked | `background` offered | both results (the output was seen) | seconds* | started in the background | waited for it (`task_output`) |
|---|---|---|---|---|---|
| hint: "it is slow, so run it in the background" | no | 4/4 | 57 | (no tool) | (no tool) |
| hint | yes | **0/4** | 22 | 4/4 | **0/4** |
| plain: "run it and count the lines" | no | 4/4 | 53 | (no tool) | (no tool) |
| plain | yes | 4/4 | 44 | 0/4 | 0/4 |

\* with another lab sharing the GPU; `scripts/tasks_lab.py latency` (no model) gives the clean numbers above.

## Options
1. **A separate tool** (`run_background`), as some agents have: clear to the model, but a second tool that must be added to every rule, hook and analysis, forever.
2. **A parameter of `run_shell`** (`background=true`): the call is the same call, judged by the same code.
3. **A process manager the model controls directly** (start, list, signal): more power, no use for it yet.

## Decision
Option 2 (`harness/tasks.py`, `harness/tools/shell.py`).

- **`run_shell(command, timeout=None, background=false)`**: `timeout` now defaults to "60 s, or 30 minutes in the background" (at most 600 s, or 2 hours). Permission rules, the shell analysis, hooks, the sandbox and the approval question all see a `run_shell` call and decide as for any command.
  When background tasks are off (setting `background_tasks`), the parameter is removed from the schema, so the model isn't offered what it can't use.
- **`task_output(task, lines, wait)`** is read-only and clearable, with the same `content_kind="command"` as `run_shell`: its result is fenced as untrusted content and may taint the chat like a command's output. `wait` lets a model with nothing else to do block (up to 120 s) for the result.
  **`task_stop(task)`** is not read-only: it asks, like any change, with a preview of what it will stop.
- **Output goes to a file in the user's folder** through a pump thread, capped at 2 MB (the command keeps running after that; the rest is dropped and counted). It never sits in the harness's memory, and a flood of output can't fill it. `--no-save` puts the files in a temporary folder.
- **At most four at once, and each has a time limit.** A task started and forgotten stops by itself. **A task never outlives the session**: on exit everything still running is stopped, with its child processes (the same process-tree kill as the timeout), and the user is told how many.
- **Being told**: a `TaskManager.poll()` returns each ended task once. The agent says it to the model **between steps** (a new `notices` hook on the loop, a user-role note from the harness), and `announce_tasks()` queues it for the next request when the user is idle. **The note carries the id, the exit
  code and the time, and never the output**: the output is text someone else may have written, and a user-role note would give it the user's authority. It reaches the model only through `task_output`.
- `/tasks`, `/tasks output ID [LINES]`, `/tasks stop ID`; the status line shows how many are running; the terminal shows `⏹ background task bg-1 ended`.

## Consequences
- A model can start a slow command and use the time. What it does with the result is up to it: it can poll with `task_output`, wait with `wait`, or, if it is a model that forgets, finish its answer while the command is still running; the user is told when it ends, and the note comes with the next request.
- Four more concurrent subprocesses, each with a pump thread: bounded, and stopped at exit. A crash of the harness itself can leave a task running (the OS reaps the pipe, not the process): the process-tree kill is best effort, as for timeouts.
- `run_shell`'s schema grew by one parameter and the two task tools cost about **220 tokens** on every request (the parameter about 50 more), measured with the harness's estimator. `background_tasks: false` removes them: the tool-search lesson (50) is the principled answer to what rarely-used tools cost.
- Background commands can't read input (stdin is closed), like foreground ones, and can't be attached to later: this is not a terminal multiplexer.
