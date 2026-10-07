"""Lesson 38: what does clearing old tool results do to a real task?

Five files of about 2,000 tokens each, in an 8,192-token window, so the five results can't all be in the
conversation at once. Two tasks:

    gather   read all five, then answer with the code word that starts each (the information has to survive
             in the conversation until the end)
    work     read each file and, right after, append its code word to summary.txt (each result is used at once)

and three variants, several runs each:

    off       no clearing: the agent stops when the window is full
    on        old results are replaced by notes
    on + rule on, and the system prompt tells the model to write down what it needs before moving on

    python scripts/micro_lab.py [--task gather|work] [--runs 3] [--files 5] [--model qwen3:4b-instruct]

Needs Ollama running with the model pulled. Works in a temporary folder; nothing in the project changes.
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import harness.session as session_module  # noqa: E402
from harness import config  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.context.tokens import estimate_tokens  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tui.plain import PlainApprover, PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

WORDS = ["amber", "birch", "cobalt", "dune", "ember", "flint", "garnet", "heron"]


class Quiet(PlainUI):
    def __call__(self, kind, data):
        pass

    def warn(self, text):
        pass


def make_files(folder: Path, count: int, rows: int = 130) -> list[str]:
    for n in range(1, count + 1):
        lines = [f"CODEWORD: {WORDS[n - 1]}"]
        lines += [f"row {i:03}: value {(i * 7919 + n * 104729) % 100000:05} status ok" for i in range(1, rows)]
        (folder / f"part{n}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return WORDS[:count]


def prompt_for(task: str, count: int) -> str:
    names = ", ".join(f"part{n}.txt" for n in range(1, count + 1))
    if task == "gather":
        return (f"Read {names}, one file at a time. Each starts with a line 'CODEWORD: <word>'. "
                "Then tell me the code word of every file.")
    return (f"For each of {names}, in that order: read it with read_file, then append one line 'partN: <word>' to summary.txt "
            "with run_shell (for example: echo 'part1: amber' >> summary.txt). <word> is the word on the file's "
            "first line 'CODEWORD: <word>'. Do one file at a time, and say 'done' at the end.")


def run_once(task: str, variant: str, count: int, model: str) -> dict:
    home = Path(tempfile.mkdtemp())
    root = home / "work"
    root.mkdir()
    words = make_files(root, count)
    config.USER_DIR = home / "user"
    settings = Settings(model=model, microcompact=variant != "off", audit_log=False, permission_mode="bypass")
    rule = session_module.CLEARING_RULE
    if variant == "on":
        session_module.CLEARING_RULE = ""             # the same clearing, without telling the model about it
    try:
        s = Session(settings, Workspace(root), Quiet(), PlainApprover())
        s.permissions.taint.trusted = True            # a throwaway folder we made: its files aren't untrusted content here
        answer = s.agent.run(prompt_for(task, count))
        calls = [c for m in s.agent.messages for c in m.tool_calls]
        summary = (root / "summary.txt").read_text(encoding="utf-8", errors="replace") if (root / "summary.txt").exists() else ""
        text = summary if task == "work" else answer
        return {"stop": s.agent.stop_reason, "found": sum(w in text.lower() for w in words),
                "reads": sum(c.name == "read_file" for c in calls), "cleared": s.agent.cleared_results}
    finally:
        session_module.CLEARING_RULE = rule
        shutil.rmtree(home, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["gather", "work"], default="gather")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--files", type=int, default=5)
    ap.add_argument("--model", default="qwen3:4b-instruct")
    args = ap.parse_args()
    probe = Path(tempfile.mkdtemp())
    make_files(probe, 1)
    one = estimate_tokens((probe / "part1.txt").read_text(encoding="utf-8"))
    shutil.rmtree(probe, ignore_errors=True)
    print(f"task '{args.task}': {args.files} files of ~{one:,} tokens each in an 8,192-token window; {args.runs} runs per variant\n")
    print(f"{'variant':<10} {'finished':>9} {'words found':>12} {'reads':>6} {'cleared':>8}   stops")
    for variant in ("off", "on", "on + rule"):
        rows = [run_once(args.task, variant, args.files, args.model) for _ in range(args.runs)]
        done = sum(r["stop"] == "completed" for r in rows)
        found = sum(r["found"] for r in rows)
        stops = ", ".join(sorted({r["stop"] for r in rows}))
        print(f"{variant:<10} {f'{done}/{len(rows)}':>9} {f'{found}/{args.files * len(rows)}':>12} "
              f"{sum(r['reads'] for r in rows) / len(rows):>6.1f} {sum(r['cleared'] for r in rows) / len(rows):>8.1f}   {stops}",
              flush=True)


if __name__ == "__main__":
    main()
