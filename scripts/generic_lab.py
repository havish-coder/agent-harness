"""Lesson 58 lab: does the agent take on work that has nothing to do with the project's files?

A user asked for a C++ trie and was told "this request is unrelated to the current project's files, goals, or context": the project's
progress journal (about fixing a Python shop) was in the system prompt. Six requests that aren't about the sample project, each in a fresh
copy of it with that journal present, approvals off (bypass) so only the model's choice is measured:

    refused   the answer says it can't or won't (I cannot / I can't / not designed / unrelated / outside ...)
    done      the file asked for exists afterwards, or (for the one request that asks for code in the answer) the answer has code

    python scripts/generic_lab.py [--runs 3] [--model qwen3:4b-instruct] [--journal on|off] [--show] [--variant as-is|only-if|only-if+last|role|role+last] [--tasks 0,1,2]

--variant: as-is is the code in this checkout. The others are the wordings tried while choosing the fix (ADR 0057), patched on top of it:
run them on a checkout of v0.8.0 to repeat the search (on today's code, "+last" would add the hand-over line a second time).
Measured: v0.8.0 refused 9 of 18 and did 7; with the fix, 0 and 17.

Needs Ollama running with the model pulled.
"""
import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness import config  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.providers.fake import committed_copy  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tui.plain import PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
TASKS = [                       # (request, the file it should produce, or None for code in the answer)
    ("Implement a Trie class in C++ (insert, search, startsWith) in trie.cpp.", "trie.cpp"),
    ("Give me C++ code to find the minimum distance between two nodes in an undirected graph.", None),
    ("Write a Rust function that reverses the order of the words in a sentence, in words.rs.", "words.rs"),
    ("Create a bash script backup.sh that copies the notes.txt file into a backup folder named with today's date.", "backup.sh"),
    ("Write a JavaScript debounce function in debounce.js.", "debounce.js"),
    ("Write a short essay (about 150 words) on why tests matter, in essay.txt.", "essay.txt"),
]
REFUSAL = re.compile(r"\b(I cannot|I can't|I can not|I'm not able|I am not able|not designed|unrelated to|outside (of )?(the )?(scope|current)|"
                     r"not (specialized|specialised)|I'm unable|I am unable)", re.IGNORECASE)
# The journal the sample folder had when the user hit this (written by earlier lab chats about the shop project), shortened.
JOURNAL = """---
trust: clean
updated: 2026-10-08T13:10:56+00:00
updated_by: web chat "In project/shop/cart.py, subtotal() ignores the quantity."
---
# Goal
Fix failing tests in the project by locating the root, running pytest, identifying the faulty code, and correcting it in the Cart class's subtotal method.
Additionally, determine the shipping cost for a 3 kg parcel to zone B using the shipping quote function.

# Done so far
- Ran tests with `cd project && python -m pytest -q`, revealing a failure in the `subtotal()` method of the `Cart` class.
- Corrected the method in `project/shop/cart.py` to multiply price by quantity; all tests pass (2 passed).

# Issues & approaches
- The issue was in the implementation, not the test.

# Current state
The `subtotal()` method in `project/shop/cart.py` is correctly implemented and all tests in `project/tests/test_cart.py` pass.

# Next steps
- Add a test in `project/tests/test_shipping.py` for the shipping cost of a 3 kg parcel to zone B.

# Key files
project/shop/cart.py
project/tests/test_cart.py
"""


JOURNAL_ONLY_IF = ("# Where we left off (only for when the user asks to continue)\nEarlier chats in this project wrote this. Use it only if the user "
                   "asks you to continue, carry on, or pick this up. Any other request is a new task, whatever its language or subject: do it "
                   "fully, and don't let this journal limit it.\n")
LAST_WORD = "\n\nThe user's next message is your task. It can be about anything, in any language: do it."
ROLE_FIRST = """You are a coding agent for any task in any programming language (C++, Rust, JavaScript, Python, shell ...): write new code and new files, fix, explain, run commands.
The workspace is where you work, not a limit on what you may do: a request doesn't have to be about the files already here, and a file that doesn't exist yet is one to create.
Use tools to inspect the workspace; never guess file contents.
Find files with glob, search inside them with grep, explore folders with list_dir.
To find where something is defined or used, grep for a likely word (e.g. grep 'timeout' to find a timeout setting).
Paths are relative to the workspace root. Be concise."""
VARIANTS = ["as-is", "only-if", "only-if+last", "role", "role+last"]


def variant(name: str) -> None:
    """Wordings tried while choosing the fix (Lesson 58). "as-is": the code in this checkout."""
    import harness.session as session
    if name.startswith("role"):
        session.ROLE = ROLE_FIRST
    if name.endswith("+last"):
        snapshot = session.workspace_snapshot
        session.workspace_snapshot = lambda *a, **k: snapshot(*a, **k) + LAST_WORD
    if name in ("only-if", "only-if+last"):
        original = session.journal_section

        def only_if(doc, fenced):
            text = original(doc, fenced)
            return JOURNAL_ONLY_IF + text.split("\n", 1)[1] + "\n(end of the journal)"
        session.journal_section = only_if


class Quiet(PlainUI):
    def __call__(self, kind, data):
        pass

    def info(self, text):
        pass

    def warn(self, text):
        pass


def run_once(request: str, wanted: str | None, model: str, journal: bool) -> dict:
    home = Path(tempfile.mkdtemp())
    root = home / "work"
    committed_copy(ROOT, "workspace", root)
    if journal:
        (root / ".harness").mkdir(exist_ok=True)
        (root / ".harness" / "progress.md").write_text(JOURNAL, encoding="utf-8")
    config.USER_DIR = home / "user"
    from harness.security.trust import set_trusted
    set_trusted(root, config.USER_DIR, True)
    settings = Settings(model=model, audit_log=False, save_chats=False, permission_mode="bypass", journal="on" if journal else "off",
                        auto_memory="off", file_history=False, todo=False, max_steps=12)
    try:
        s = Session(settings, Workspace(root), Quiet(), None)
        s.agent.stream = False
        answer = s.agent.run(request)
        written = bool(wanted) and any(p.is_file() for p in root.rglob(wanted))        # anywhere: project/essay.txt counts too
        refused = bool(REFUSAL.search(answer)) and not written
        done = written if wanted else ("```" in answer or "#include" in answer)
        return {"refused": refused, "done": done, "answer": " ".join(answer.split())[:160]}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--model", default="qwen3:4b-instruct")
    ap.add_argument("--journal", default="on", choices=["on", "off"])
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--variant", default="as-is", choices=VARIANTS)
    ap.add_argument("--tasks", default="", help="which requests, by number from 0 (default: all six)")
    args = ap.parse_args()
    variant(args.variant)
    chosen = [TASKS[int(i)] for i in args.tasks.split(",")] if args.tasks else TASKS
    print(f"{args.runs} runs per request, {args.model}, journal {args.journal}, wording {args.variant}\n")
    total = {"refused": 0, "done": 0, "n": 0}
    for request, wanted in chosen:
        rows = [run_once(request, wanted, args.model, args.journal == "on") for _ in range(args.runs)]
        refused, done = sum(r["refused"] for r in rows), sum(r["done"] for r in rows)
        total["refused"] += refused
        total["done"] += done
        total["n"] += len(rows)
        print(f"refused {refused}/{len(rows)}  done {done}/{len(rows)}  {request[:70]}", flush=True)
        if args.show:
            for r in rows:
                print(f"      {'REFUSED' if r['refused'] else 'ok':<8} {r['answer']}")
    print(f"\nall: refused {total['refused']}/{total['n']}, done {total['done']}/{total['n']}")


if __name__ == "__main__":
    main()
