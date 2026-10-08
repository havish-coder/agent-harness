"""Lesson 48: background tasks. Start a long command, keep working, hear when it ends.

`run_shell` blocks: the agent waits, the user waits, and a 4B model waiting on a ten-minute test run has nothing to do but time out. With `background=true` the command starts and
`run_shell` returns at once with an id; the agent goes on with something else, and the harness tells it when the command ends.

    run_shell(command="python -m pytest -q", background=true)  ->  "Started background task bg-1 ..."
    ... the agent does other things ...
    [Note from the harness: background task bg-1 finished (exit code 1, 42 s). task_output shows what it printed.]
    task_output(task="bg-1")  ->  the end of its output
    task_stop(task="bg-1")     ->  stops it, and everything it started

It is a **parameter of `run_shell`, not a second tool**, on purpose. Every rule that decides whether a command may run (deny rules, the command analysis, hooks, the sandbox, the
approval question) is written about `run_shell`; a separate `run_background` tool would be a way round all of them. As a parameter, a background command is the same command, judged the same way.

What the harness takes care of:
  * **Output goes to a file** in your user folder (`projects/<project>/tasks/`), not to memory: a command that prints for an hour can't fill the process, and the file is capped (2 MB; after that
    the command keeps running and what it prints is dropped, and `task_output` says so).
  * **At most four at once**, each with a time limit (30 minutes by default, 2 hours at most): a command started and forgotten stops by itself.
  * **A task never outlives the session.** When the chat ends, everything still running is stopped, with its children: nothing is left running on your machine that you haven't been told about.
  * **The notice says that it ended and how, not what it printed.** What a command printed is text someone else may have written (a test's failure message can carry anything), so it reaches the model only through
    `task_output`, which is fenced and tracked as untrusted like the output of `run_shell`.
  * **Told once.** Each task that ends is reported once: to the model between steps if a request is running, or with its next request if you were idle; to you on the screen either way.
"""
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from harness.security.sandbox import Sandbox
from harness.tools.shell import DEFAULT_LIMIT, TAIL_LINES, Shell, child_env, clip, kill_tree

MAX_TASKS = 4
MAX_LIMIT = 7_200
MAX_WAIT = 120                   # the longest task_output waits for a task to end
LOG_CAP = 2_000_000              # bytes of output kept per task
OUTPUT_BUDGET = 6_000            # characters task_output returns


@dataclass
class Task:
    id: str
    command: str
    started: float
    log: Path
    limit: int
    proc: subprocess.Popen | None = None
    ended: float | None = None
    code: int | None = None
    status: str = "running"            # running, exited, stopped, timed out
    notified: bool = False
    dropped: int = 0                   # bytes of output not kept because the log was full
    thread: threading.Thread | None = field(default=None, repr=False)

    @property
    def running(self) -> bool:
        return self.status == "running"

    @property
    def seconds(self) -> float:
        return (self.ended or time.monotonic()) - self.started

    def describe(self) -> str:
        if self.running:
            return f"running for {self.seconds:.0f} s"
        if self.status == "exited":
            return f"exit code {self.code}" + (" (success)" if self.code == 0 else " (failure)") + f", {self.seconds:.0f} s"
        return f"{self.status} after {self.seconds:.0f} s"


class TaskManager:
    """The background tasks of one session."""

    def __init__(self, directory: Path | str, limit: int = MAX_TASKS):
        self.directory = Path(directory)
        self.limit = limit
        self.tasks: dict[str, Task] = {}
        self.count = 0
        self.lock = threading.Lock()

    # -- starting ----------------------------------------------------------------------------------
    def start(self, shell: Shell, command: str, cwd: Path, limit: int = DEFAULT_LIMIT, env_keep=(), sandbox: Sandbox | None = None,
              network: bool = True) -> Task:
        """Start `command` and return at once. Raises ValueError when four are already running."""
        with self.lock:
            if sum(t.running for t in self.tasks.values()) >= self.limit:
                raise ValueError(f"{self.limit} background tasks are already running: wait for one, or stop one with task_stop")
            self.count += 1
            task_id = f"bg-{self.count}"
            self.directory.mkdir(parents=True, exist_ok=True)
            log = self.directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{task_id}.log"
        argv = shell.command_line(command)
        if sandbox is not None:
            argv = sandbox.wrap(argv, cwd, cwd, network)
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(argv, cwd=cwd, env=child_env(env_keep), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        task = Task(task_id, command, time.monotonic(), log, max(1, min(int(limit), MAX_LIMIT)), proc)
        task.thread = threading.Thread(target=self.watch, args=(task,), daemon=True, name=f"task-{task_id}")
        with self.lock:
            self.tasks[task_id] = task
        task.thread.start()
        return task

    def watch(self, task: Task) -> None:
        """Copy the command's output to its log file (up to the cap), enforce the time limit, record how it ended."""
        pump = threading.Thread(target=self.pump, args=(task,), daemon=True)
        pump.start()
        try:
            task.proc.wait(timeout=task.limit)
            with self.lock:
                if task.running:
                    task.code, task.status = task.proc.returncode, "exited"
        except subprocess.TimeoutExpired:
            kill_tree(task.proc)
            with self.lock:
                if task.running:
                    task.status = "timed out"
        pump.join(timeout=2)
        with self.lock:
            task.ended = time.monotonic()
            if task.running:
                task.status = "stopped"

    def pump(self, task: Task) -> None:
        written = 0
        with task.log.open("wb") as f:
            for chunk in iter(lambda: task.proc.stdout.read1(8192) if hasattr(task.proc.stdout, "read1") else task.proc.stdout.read(8192), b""):
                room = LOG_CAP - written
                if room > 0:
                    f.write(chunk[:room])
                    f.flush()
                    written += min(len(chunk), room)
                task.dropped += max(0, len(chunk) - max(room, 0))

    # -- looking -----------------------------------------------------------------------------------
    def get(self, ref: str) -> Task | None:
        ref = (ref or "").strip().lower()
        if ref.isdigit():
            ref = f"bg-{ref}"
        return self.tasks.get(ref)

    def listing(self) -> str:
        if not self.tasks:
            return "no background tasks"
        return "\n".join(f"{t.id:<6} {t.describe():<28} {t.command[:80]}" for t in self.tasks.values())

    def output(self, task: Task, tail: int = TAIL_LINES) -> str:
        """The status line, and the last `tail` lines the task printed."""
        data = task.log.read_bytes() if task.log.exists() else b""
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
        lines = text.rstrip("\n").split("\n") if text.strip() else []
        shown = lines[-max(1, tail):]
        body = clip("\n".join(shown), OUTPUT_BUDGET) if shown else "(no output yet)" if task.running else "(no output)"
        cut = f"(showing the last {len(shown)} of {len(lines)} lines)\n" if len(shown) < len(lines) else ""
        full = f"(the log was full at {LOG_CAP // 1_000_000} MB: {task.dropped:,} more bytes were not kept)\n" if task.dropped else ""
        return f"{task.id}: {task.describe()} · {task.command[:100]}\n{cut}{full}{body}"

    def wait(self, task: Task, seconds: float) -> bool:
        """Wait up to `seconds` for a task to end. True when it has."""
        deadline = time.monotonic() + max(0.0, seconds)
        while task.running and time.monotonic() < deadline:
            time.sleep(0.05)
        return not task.running

    def poll(self) -> list[Task]:
        """Tasks that have ended since the last call, once each."""
        with self.lock:
            done = [t for t in self.tasks.values() if not t.running and not t.notified]
            for t in done:
                t.notified = True
        return done

    # -- stopping ----------------------------------------------------------------------------------
    def stop(self, task: Task) -> bool:
        """Stop a running task and its children. False if it had already ended."""
        with self.lock:
            if not task.running:
                return False
            task.status = "stopped"
        kill_tree(task.proc)
        if task.thread is not None:
            task.thread.join(timeout=3)
        return True

    def close(self) -> int:
        """The session is over: stop everything still running. Returns how many were stopped."""
        stopped = 0
        for t in list(self.tasks.values()):
            stopped += self.stop(t)
        return stopped
