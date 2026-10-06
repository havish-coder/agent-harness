"""Lesson 13: the shell tool reports exit codes, keeps the end of long output, and enforces timeouts."""
import sys
import time

import pytest

from harness.tools.shell import OUTPUT_BUDGET, clip, detect_shell, make_shell_tools
from harness.workspace import Workspace

PY = f'"{sys.executable}"' if " " in sys.executable else sys.executable
if detect_shell().name.startswith(("PowerShell", "Windows PowerShell")):
    PY = "& " + PY          # PowerShell needs the call operator for a quoted program path


@pytest.fixture
def run(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "hello.txt").write_text("hi", encoding="utf-8")
    shell = {t.name: t for t in make_shell_tools(Workspace(tmp_path))}["run_shell"]
    return shell.fn


def py(code: str) -> str:
    return f"{PY} -c \"{code}\""


def test_success_and_output(run):
    out = run(command=py("print('hello')"))
    assert out.startswith("exit code 0 (success)")
    assert "--- stdout ---\nhello" in out


def test_real_exit_codes_and_stderr(run):
    out = run(command=py("import sys; print('oops', file=sys.stderr); sys.exit(3)"))
    assert out.startswith("exit code 3 (failure)")
    assert "--- stderr ---\noops" in out


def test_utf8_output(run):
    assert "café ✓" in run(command=py("print('caf\\u00e9 \\u2713')"))


def test_runs_in_the_workspace_root(run):
    out = run(command=py("import os; print(sorted(os.listdir()))"))
    assert "['sub']" in out and "in ." in out


def test_no_stdin(run):
    out = run(command=py("input('password: ')"))
    assert "EOFError" in out and "exit code 1" in out


def test_timeout_kills_the_command(run):
    start = time.monotonic()
    out = run(command=py("import time; time.sleep(30)"), timeout=2)
    assert out.startswith("TIMED OUT after 2 s")
    assert time.monotonic() - start < 15


def test_no_output(run):
    assert run(command=py("pass")).endswith("(no output)")


def test_clip_keeps_more_of_the_end():
    text = "".join(f"line {i}\n" for i in range(5000))
    out = clip(text, 1000)
    assert out.startswith("line 0\n") and out.rstrip().endswith("line 4999")
    head, _, tail = out.partition("... [")
    assert len(tail) > 2 * len(head)
    assert len(clip("short", OUTPUT_BUDGET)) == 5


def test_description_names_the_shell(tmp_path):
    tool = make_shell_tools(Workspace(tmp_path))[0]
    assert "Shell: " in tool.description
    assert not tool.is_read_only({"command": "ls"})      # every command needs approval (for now)
