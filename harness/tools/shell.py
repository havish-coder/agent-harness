"""Lesson 13: running commands. The most powerful tool, and the most dangerous one.

Any command the user approves runs with the user's full rights. Module 5 hardens what
surrounds it: permissions read the command before it runs (harness/security/shell.py, Lesson 30),
and secret environment variables are removed from the environment it runs in (Lesson 30). What
it got right from the start: a timeout that kills the whole process tree, no stdin (so nothing waits for input),
UTF-8 output on Windows, output caps that keep the end, and an exit code the model can't miss.
"""
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from harness.security.sandbox import Sandbox
from harness.security.secrets import scrub_env
from harness.tools.base import Tool, tool
from harness.workspace import Workspace

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600
DEFAULT_LIMIT = 1_800       # seconds a background task may run (Lesson 48)
TAIL_LINES = 40            # lines task_output shows by default
OUTPUT_BUDGET = 7_000      # characters of output returned to the model
HEAD_SHARE = 0.3           # keep 30% from the start, 70% from the end (summaries are at the end)


@dataclass
class Shell:
    name: str           # shown to the model, e.g. "Windows PowerShell 5.1"
    argv: list[str]     # the program and its flags; the wrapped command is the last argument
    hint: str           # syntax advice for this shell
    prefix: str = ""    # added before the user's command
    suffix: str = ""    # added after it

    def command_line(self, command: str) -> list[str]:
        return self.argv + [self.prefix + command + self.suffix]

    @property
    def dialect(self) -> str:
        """How permission rules should read commands for this shell: "posix" or "powershell"."""
        return "powershell" if self.prefix else "posix"


# PowerShell: UTF-8 in and out (otherwise symbols come back as '?'), and a real exit code.
# Without the suffix, `python -c "exit(3)"` reports exit code 1: PowerShell only says pass/fail.
PS_PREFIX = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $OutputEncoding=[System.Text.Encoding]::UTF8; "
PS_SUFFIX = "\n$__ok = $?; if ($__ok) { exit 0 } elseif ($LASTEXITCODE) { exit $LASTEXITCODE } else { exit 1 }"
PS_FLAGS = ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]


def find_git_bash() -> Path | None:
    """Git for Windows' bash.exe (never System32's bash.exe, which starts WSL)."""
    candidates = []
    git = shutil.which("git")
    if git:
        candidates += [parent / "bin" / "bash.exe" for parent in Path(git).parents]
    candidates.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe")
    return next((c for c in candidates if c.exists()), None)


def detect_shell(preference: str | None = None) -> Shell:
    """bash wherever possible (models know it best), else PowerShell. HARNESS_SHELL overrides."""
    preference = (preference or os.environ.get("HARNESS_SHELL", "")).lower()
    if os.name == "nt":
        bash = find_git_bash() if preference in ("", "bash") else None
        if bash:
            return Shell("bash (Git for Windows)", [str(bash), "-c"],
                         "POSIX shell syntax; chain commands with '&&'. Windows paths also work with "
                         "forward slashes (C:/Users/...).")
        pwsh = shutil.which("pwsh") if preference in ("", "pwsh", "powershell") else None
        if pwsh and preference != "powershell":
            return Shell("PowerShell 7", [pwsh, *PS_FLAGS], "PowerShell syntax; chain commands with ';' or '&&'.",
                         PS_PREFIX, PS_SUFFIX)
        return Shell("Windows PowerShell 5.1", ["powershell.exe", *PS_FLAGS],
                     "PowerShell syntax. Chain commands with ';' ('&&' does not work in this version). "
                     "Use Get-ChildItem, Select-String, $env:NAME instead of ls -la, grep, $NAME.",
                     PS_PREFIX, PS_SUFFIX)
    bash = shutil.which("bash") or "/bin/sh"
    return Shell(Path(bash).name, [bash, "-c"], "POSIX shell syntax; chain commands with '&&'.")


def child_env(keep=()) -> dict:
    """The environment for commands: ours without secrets (API keys, tokens, passwords: Lesson 30),
    plus UTF-8 Python and our Python first on PATH. `keep` names variables to leave in."""
    env, _ = scrub_env(dict(os.environ), keep)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop the command AND everything it started (a test runner's workers, a dev server...)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def clip(text: str, budget: int) -> str:
    """Keep the start and (mostly) the end of long output, and say what was cut."""
    if len(text) <= budget:
        return text
    head = int(budget * HEAD_SHARE)
    tail = budget - head
    cut = text[head:len(text) - tail]
    return (f"{text[:head]}\n... [{len(cut):,} characters, {cut.count(chr(10)):,} lines cut] ...\n"
            f"{text[len(text) - tail:]}")


def run_command(shell: Shell, command: str, cwd: Path, timeout: int, env_keep=(), sandbox: Sandbox | None = None,
                network: bool = True) -> tuple[int | None, str, str, float]:
    """Run one command. Returns (exit code or None on timeout, stdout, stderr, seconds). With a sandbox
    (Lesson 35) the command runs inside it: writes only in the workspace, protected folders read-only."""
    argv = shell.command_line(command)
    if sandbox is not None:
        argv = sandbox.wrap(argv, cwd, cwd, network)
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    start = time.monotonic()
    proc = subprocess.Popen(argv, cwd=cwd, env=child_env(env_keep), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        out, err = proc.communicate()
        code = None
    return (code, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace"),
            time.monotonic() - start)


def make_shell_tools(ws: Workspace, shell: Shell | None = None, env_keep=(), sandbox: Sandbox | None = None,
                     sandbox_network: bool = True, sandbox_required: bool = False, tasks=None) -> list[Tool]:
    """`tasks` (Lesson 48) is the session's TaskManager; without one, `background` is refused and there are no task tools."""
    shell = shell or detect_shell()

    @tool(read_only=False, concurrency_safe=False, max_result_chars=OUTPUT_BUDGET + 1_000, content_kind="command", clearable=True)
    def run_shell(command: str, timeout: int | None = None, background: bool = False) -> str:
        """Run a shell command in the workspace root folder and return its exit code and output.

        Use it to run tests, scripts, git, package managers and build tools. To read, search or
        edit files, use read_file, grep, glob and edit_file instead. Commands can't read input:
        anything that waits for a key press or a password fails immediately. Environment variables
        that hold secrets (names with KEY, TOKEN, SECRET, PASSWORD) are not available to commands.

        Args:
            command: The command to run. Paths are relative to the workspace root.
            timeout: Seconds before the command is stopped (default 60, at most 600; for a background task default 1800, at most 7200).
            background: Start it and return at once with a task id, for a command that takes long (tests, a build). You are told when it ends; task_output shows its output.
        """
        folder = ws.root
        if sandbox is None and sandbox_required:
            return ("Error: commands are switched off: the settings require a sandbox and this machine has none "
                    "(sandbox: \"on\"). Tell the user.")
        if background:
            if tasks is None:
                return "Error: background tasks aren't available in this session: run the command without background."
            task = tasks.start(shell, command, folder, limit=DEFAULT_LIMIT if timeout is None else timeout, env_keep=env_keep,
                               sandbox=sandbox, network=sandbox_network)
            return (f"Started background task {task.id}: {command[:100]}\nIt runs on while you do other things, and you will be told when it ends. "
                    f"task_output(task='{task.id}') shows what it has printed; task_stop(task='{task.id}') stops it.")
        timeout = max(1, min(DEFAULT_TIMEOUT if timeout is None else timeout, MAX_TIMEOUT))
        code, out, err, seconds = run_command(shell, command, folder, timeout, env_keep, sandbox, sandbox_network)

        if code is None:
            status = f"TIMED OUT after {timeout} s; the command and its child processes were stopped"
        else:
            status = f"exit code {code}" + (" (success)" if code == 0 else " (failure)")
        parts = [f"{status} · {seconds:.1f} s · in {ws.display(folder)}"]
        out, err = out.strip("\n"), err.strip("\n")
        if out:
            parts.append("--- stdout ---\n" + clip(out, OUTPUT_BUDGET if not err else OUTPUT_BUDGET * 2 // 3))
        if err:
            parts.append("--- stderr ---\n" + clip(err, OUTPUT_BUDGET if not out else OUTPUT_BUDGET // 3))
        if not out and not err:
            parts.append("(no output)")
        return "\n".join(parts)

    run_shell.dialect = shell.dialect
    run_shell.description += f"\n\nShell: {shell.name}. {shell.hint}"
    if sandbox is not None:
        run_shell.description += "\n\n" + sandbox.describe(sandbox_network).capitalize() + "."
    if tasks is None:
        run_shell.parameters["properties"].pop("background", None)       # nothing to run in the background with: don't offer it
        return [run_shell]

    def find(ref: str):
        task = tasks.get(ref)
        if task is None:
            known = ", ".join(tasks.tasks) or "none started"
            raise ValueError(f"there is no background task '{ref}' (tasks: {known})")
        return task

    @tool(deferrable=True, read_only=True, concurrency_safe=True, max_result_chars=OUTPUT_BUDGET + 1_000, content_kind="command", clearable=True)
    def task_output(task: str, lines: int = TAIL_LINES, wait: int = 0) -> str:
        """Show the end of a background task's output, and whether it is still running.

        Args:
            task: The task id, like bg-1.
            lines: How many of the last lines to show.
            wait: Seconds to wait for it to end first (up to 120): use it when you have nothing else to do and need the result.
        """
        found = find(task)
        if wait > 0:
            tasks.wait(found, min(int(wait), 120))
        return tasks.output(found, max(1, min(int(lines), 400)))

    @tool(deferrable=True, read_only=False, concurrency_safe=False)
    def task_stop(task: str) -> str:
        """Stop a background task you started, and everything it started.

        Args:
            task: The task id, like bg-1.
        """
        found = find(task)
        return f"Stopped {found.id}." if tasks.stop(found) else f"{found.id} had already ended: {found.describe()}."

    task_stop.preview = lambda task: f"stop background task {task}: {(tasks.get(task).command[:80] if tasks.get(task) else 'unknown')}"
    return [run_shell, task_output, task_stop]
