"""Lessons 38 and 39: what do clearing old results and summarising the conversation do to a real task?

Five files of about 2,000 tokens each, in an 8,192-token window, so the five results can't all be in the
conversation at once. Two tasks:

    gather   read all five, then answer with the code word that starts each (the information has to survive
             in the conversation until the end)
    work     read each file and, right after, append its code word to summary.txt (each result is used at once)

and these variants, several runs each:

    off           neither: the agent stops when the window is full
    clear         old results are replaced by notes (Lesson 38), and the prompt tells the model about it
    clear-norule  the same, without the sentence in the system prompt
    summarise     the older conversation is summarised by the model when the window nearly fills (Lesson 39)
    summarise-plain  the same, without the line telling the model to cover the whole request
    both          clearing first, then summarising if that isn't enough

    python scripts/micro_lab.py [--task gather|work] [--runs 3] [--files 5] [--variants off,clear,summarise,both]
                                [--model qwen3:4b-instruct]

Needs Ollama running with the model pulled. Works in a temporary folder; nothing in the project changes.
"""
import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import harness.context.compact as compact_module  # noqa: E402
import harness.session as session_module  # noqa: E402
from harness import config  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.context.tokens import estimate_tokens  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tui.plain import PlainApprover, PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

WORDS = ["amber", "birch", "cobalt", "dune", "ember", "flint", "garnet", "heron"]
# name -> (microcompact, auto_compact, the system-prompt sentence about notes, the "carry on" line in the summary message)
VARIANTS = {"off": (False, False, True, True), "clear": (True, False, True, True), "clear-norule": (True, False, False, True),
            "summarise": (False, True, True, True), "summarise-plain": (False, True, True, False), "both": (True, True, True, True)}


class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.started = 0.0
        self.summary_secs: list[float] = []            # how long each summary took the model

    def __call__(self, kind, data):
        if kind == "compacting":
            self.started = time.perf_counter()
        elif kind in ("compact", "compact_failed") and self.started:
            self.summary_secs.append(time.perf_counter() - self.started)
            self.started = 0.0

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
    clear, summarise, rule, nudge = VARIANTS[variant]
    settings = Settings(model=model, microcompact=clear, auto_compact=summarise, audit_log=False, permission_mode="bypass")
    saved_rule, saved_note = session_module.CLEARING_RULE, compact_module.CONTINUE_NOTE
    if not rule:
        session_module.CLEARING_RULE = ""             # the same clearing, without telling the model about it
    if not nudge:
        compact_module.CONTINUE_NOTE = ""
    try:
        ui = Quiet()
        s = Session(settings, Workspace(root), ui, PlainApprover())
        s.permissions.taint.trusted = True            # a throwaway folder we made: its files aren't untrusted content here
        answer = s.agent.run(prompt_for(task, count))
        calls = [c for m in [*s.agent.archive, *s.agent.messages] for c in m.tool_calls]     # summarised messages too
        summary = (root / "summary.txt").read_text(encoding="utf-8", errors="replace") if (root / "summary.txt").exists() else ""
        text = summary if task == "work" else answer
        return {"stop": s.agent.stop_reason, "found": sum(w in text.lower() for w in words),
                "reads": sum(c.name == "read_file" for c in calls), "cleared": s.agent.cleared_results,
                "summaries": s.agent.compactions, "secs": ui.summary_secs}
    finally:
        session_module.CLEARING_RULE, compact_module.CONTINUE_NOTE = saved_rule, saved_note
        shutil.rmtree(home, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["gather", "work"], default="gather")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--files", type=int, default=5)
    ap.add_argument("--variants", default="off,clear,summarise,both")
    ap.add_argument("--model", default="qwen3:4b-instruct")
    args = ap.parse_args()
    probe = Path(tempfile.mkdtemp())
    make_files(probe, 1)
    one = estimate_tokens((probe / "part1.txt").read_text(encoding="utf-8"))
    shutil.rmtree(probe, ignore_errors=True)
    print(f"task '{args.task}': {args.files} files of ~{one:,} tokens each in an 8,192-token window; {args.runs} runs per variant\n")
    print(f"{'variant':<16} {'finished':>9} {'words found':>12} {'reads':>6} {'cleared':>8} {'summaries':>10} {'s each':>7}   stops")
    for variant in args.variants.split(","):
        rows = [run_once(args.task, variant, args.files, args.model) for _ in range(args.runs)]
        done = sum(r["stop"] == "completed" for r in rows)
        found = sum(r["found"] for r in rows)
        stops = ", ".join(sorted({r["stop"] for r in rows}))
        mean = len(rows)
        secs = [x for r in rows for x in r["secs"]]
        print(f"{variant:<16} {f'{done}/{mean}':>9} {f'{found}/{args.files * mean}':>12} "
              f"{sum(r['reads'] for r in rows) / mean:>6.1f} {sum(r['cleared'] for r in rows) / mean:>8.1f} "
              f"{sum(r['summaries'] for r in rows) / mean:>10.1f} {(sum(secs) / len(secs) if secs else 0):>7.1f}   {stops}", flush=True)


if __name__ == "__main__":
    main()
