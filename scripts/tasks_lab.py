"""Lesson 48: background tasks. What do they cost, and does a small model use them?

    python scripts/tasks_lab.py latency                           (no model) how long starting takes, against running to the end
    python scripts/tasks_lab.py choose [--runs 4] [--model ...] [--show] [--only hint/background]   a slow command and a quick job, asked two ways, with and without the tool

The request has two jobs: run a command that takes 25 seconds (`python -c "import time; time.sleep(25); print('build ok')"`), and count the lines of notes.txt that
start with TODO (three). Asked

    hint     "it is slow, so run it in the background"
    plain    just "run it and count the lines"

with the agent given `background` (tasks on) or not (blocking only). What is counted: the answer has both results (3 and "build ok"), how long it took,
whether the model started the command in the background, and whether it waited for it with task_output.

Needs Ollama running with the model pulled.
"""
import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from todo_lab import REPO, SaysYes  # noqa: E402

from harness import config  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.providers.fake import committed_copy  # noqa: E402
from harness.security.trust import set_trusted  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tools.shell import detect_shell  # noqa: E402
from harness.tui.plain import PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

SLOW = "python -c \"import time; time.sleep(25); print('build ok')\""
PROMPTS = {
    "hint": f"Two jobs. 1) Run `{SLOW}`: it is slow, so run it in the background. 2) While it runs, count the lines of notes.txt that start with TODO. Then tell me both results.",
    "plain": f"Run `{SLOW}` and count the lines of notes.txt that start with TODO. Tell me both results.",
}


class Quiet(PlainUI):
    def __call__(self, kind, data):
        pass

    def warn(self, text):
        pass

    def info(self, text):
        pass


def latency() -> None:
    from harness.tasks import TaskManager
    from harness.tools.shell import run_command
    home = Path(tempfile.mkdtemp())
    try:
        shell, cwd = detect_shell(), home
        manager = TaskManager(home / "tasks")
        command = "python -c \"import time; time.sleep(3); print('x')\""
        started = time.perf_counter()
        task = manager.start(shell, command, cwd)
        began = time.perf_counter() - started
        manager.wait(task, 10)
        total_bg = time.perf_counter() - started
        started = time.perf_counter()
        run_command(shell, command, cwd, 30)
        blocking = time.perf_counter() - started
        print(f"a command that takes 3 s: blocking run {blocking:.2f} s; background start returned after {began * 1000:.0f} ms, and it ended at {total_bg:.2f} s")
        manager.close()
    finally:
        shutil.rmtree(home, ignore_errors=True)


def run_once(prompt: str, background: bool, model: str) -> dict:
    home = Path(tempfile.mkdtemp())
    root = home / "work"
    committed_copy(REPO, "workspace", root)
    config.USER_DIR = home / "user"
    set_trusted(root, config.USER_DIR, True)
    settings = Settings(model=model, audit_log=False, save_chats=False, permission_mode="bypass", journal="off", auto_memory="off", file_history=False,
                        todo=False, subagents=False, max_steps=12, background_tasks=background)
    try:
        s = Session(settings, Workspace(root), Quiet(), SaysYes())
        started = time.monotonic()
        answer = s.agent.run(prompt)
        seconds = time.monotonic() - started
        calls = [c for m in s.agent.messages for c in m.tool_calls]
        s.close()
        # did the command's output ever reach the model? (a blocking run, or task_output after it ended). The command's own text, which a background
        # start echoes back, says print('build ok') too: that is not its output.
        saw = any("build ok" in m.content.replace("print('build ok')", "") for m in s.agent.messages if m.role == "tool")
        return {"right": "3" in answer and saw and "build ok" in answer.lower(), "seconds": seconds,
                "background": any(c.name == "run_shell" and c.arguments.get("background") for c in calls),
                "waited": any(c.name == "task_output" and int(c.arguments.get("wait", 0) or 0) > 0 for c in calls),
                "polled": sum(c.name == "task_output" for c in calls), "calls": len(calls), "stop": s.agent.stop_reason,
                "saw": saw, "text": " ".join(answer.split())[:300]}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def choose(runs: int, model: str, show: bool = False, only: str = "") -> None:
    print(f"{runs} runs per row, {model}\n")
    print(f"{'asked':<7} {'tool':<11} {'both results':>13} {'saw the output':>15} {'seconds':>8} {'in background':>14} {'waited':>7} {'task_output calls':>18} {'tool calls':>11}")
    for key, prompt in PROMPTS.items():
        for background in (False, True):
            if only and only != f"{key}/{'background' if background else 'blocking'}":
                continue
            rows = [run_once(prompt, background, model) for _ in range(runs)]
            n = len(rows)
            print(f"{key:<7} {'background' if background else 'blocking':<11} {sum(r['right'] for r in rows):>10}/{n:<2} {sum(r['saw'] for r in rows):>12}/{n:<2} {sum(r['seconds'] for r in rows) / n:>8.0f} "
                  f"{sum(r['background'] for r in rows):>11}/{n:<2} {sum(r['waited'] for r in rows):>5}/{n:<1} {sum(r['polled'] for r in rows) / n:>18.1f} "
                  f"{sum(r['calls'] for r in rows) / n:>11.1f}", flush=True)
            if show:
                for r in rows:
                    print(f"    {r['text']}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["latency", "choose"])
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--model", default="qwen3:4b-instruct")
    ap.add_argument("--show", action="store_true", help="print each answer")
    ap.add_argument("--only", default="", help="one row, e.g. hint/background")
    args = ap.parse_args()
    latency() if args.task == "latency" else choose(args.runs, args.model, args.show, args.only)


if __name__ == "__main__":
    main()
