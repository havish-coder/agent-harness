"""Lesson 13: running commands. The most powerful tool, and the most dangerous one.

Naive on purpose: any command the user approves runs with the user's full rights. Module 5
hardens it (command analysis, permissions, environment scrubbing). What it does get right
already: a timeout that kills the whole process tree, no stdin (so nothing waits for input),
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

from harness.tools.base import Tool, tool
from harness.workspace import Workspace

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600
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


def child_env() -> dict:
    """The environment for commands: ours, plus UTF-8 Python and our Python first on PATH."""
    env = dict(os.environ)
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


def run_command(shell: Shell, command: str, cwd: Path, timeout: int) -> tuple[int | None, str, str, float]:
    """Run one command. Returns (exit code or None on timeout, stdout, stderr, seconds)."""
    argv = shell.command_line(command)
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    start = time.monotonic()
    proc = subprocess.Popen(argv, cwd=cwd, env=child_env(), stdin=subprocess.DEVNULL,
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


def make_shell_tools(ws: Workspace, shell: Shell | None = None) -> list[Tool]:
    shell = shell or detect_shell()

    @tool(read_only=False, concurrency_safe=False, max_result_chars=OUTPUT_BUDGET + 1_000)
    def run_shell(command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        """Run a shell command in the workspace root folder and return its exit code and output.

        Use it to run tests, scripts, git, package managers and build tools. To read, search or
        edit files, use read_file, grep, glob and edit_file instead. Commands can't read input:
        anything that waits for a key press or a password fails immediately.

        Args:
            command: The command to run. Paths are relative to the workspace root.
            timeout: Seconds before the command is stopped (at most 600).
        """
        folder = ws.root
        timeout = max(1, min(timeout, MAX_TIMEOUT))
        code, out, err, seconds = run_command(shell, command, folder, timeout)

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

    run_shell.description += f"\n\nShell: {shell.name}. {shell.hint}"
    return [run_shell]
