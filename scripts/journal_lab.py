"""Lesson 42b: does a new chat pick up where the last one stopped, with and without the project journal?

Two separate sessions (as two terminal runs would be) in a throwaway copy of the sample project:

    session 1  "Fix the subtotal bug in project/shop/cart.py. That is all for this chat. The next job, in the next chat, is a test in
               project/tests/test_cart.py that adding quantity 0 raises ValueError."       (then the chat ends)
    session 2  "Please continue."          a new Session, no saved chat resumed

    journal    the progress journal is on: session 1 writes it, session 2 starts from it
    none       no journal: session 2 knows nothing about session 1

For each run: did the remaining test get written (ValueError in tests/test_cart.py)? did the project's tests pass at the end? did session 2
re-do the fix (edit cart.py again) or re-read it? how many tool calls did it use?

    python scripts/journal_lab.py [--runs 3] [--variants journal,none] [--model qwen3:4b-instruct]

Needs Ollama running with the model pulled. Each journal update is a model call (about half a minute on a small GPU).
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import config  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.providers.fake import committed_copy  # noqa: E402
from harness.security.trust import set_trusted  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tui.plain import PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FIRST = ("Fix the subtotal bug in project/shop/cart.py: it ignores the quantity. That is all for this chat. "
         "The next job, in the next chat, is a test in project/tests/test_cart.py that adding quantity 0 raises ValueError.")
SECOND = "Please continue."


class Quiet(PlainUI):
    def __call__(self, kind, data):
        pass

    def warn(self, text):
        pass

    def info(self, text):
        pass


class SaysYes:
    pause = None

    def __call__(self, call, tool, decision=None):
        return True


def calls(session):
    return [c for m in session.agent.messages for c in m.tool_calls]


def pytest_passes(project: Path) -> bool:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=project, capture_output=True, text=True)
    return r.returncode == 0


def run_once(variant: str, model: str) -> dict:
    home = Path(tempfile.mkdtemp())
    root = home / "work"
    committed_copy(REPO, "workspace", root)
    if "sum(price for" not in (root / "project" / "shop" / "cart.py").read_text(encoding="utf-8"):
        raise SystemExit("workspace/project/shop/cart.py doesn't have the demo bug any more (an agent run fixed it?): git checkout it first")
    config.USER_DIR = home / "user"
    set_trusted(root, config.USER_DIR, True)
    settings = dict(model=model, audit_log=False, save_chats=False, permission_mode="bypass", journal="on" if variant == "journal" else "off",
                    auto_memory="off")
    test_file = root / "project" / "tests" / "test_cart.py"
    try:
        one = Session(Settings(**settings), Workspace(root), Quiet(), SaysYes())
        one.agent.run(FIRST)
        one.after_turn()
        one.close()
        s1_did_test = "ValueError" in test_file.read_text(encoding="utf-8")
        journal = (root / ".harness" / "progress.md").read_text(encoding="utf-8") if (root / ".harness" / "progress.md").exists() else ""
        two = Session(Settings(**settings), Workspace(root), Quiet(), SaysYes())
        two.agent.run(SECOND)
        used = calls(two)
        return {"journal_text": journal, "s1_did_test": s1_did_test, "journal": bool(journal), "journal_mentions": "ValueError" in journal,
                "test_written": "ValueError" in test_file.read_text(encoding="utf-8") and not s1_did_test,
                "passes": pytest_passes(root / "project"),
                "redid_fix": any(c.name == "edit_file" and "cart.py" in str(c.arguments.get("path", "")) for c in used),
                "reread": any(c.name == "read_file" and "cart.py" in str(c.arguments.get("path", "")) for c in used),
                "calls": len(used), "asked": two.agent.messages[-1].content[:90].replace("\n", " ")}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--variants", default="journal,none")
    ap.add_argument("--model", default="qwen3:4b-instruct")
    ap.add_argument("--show", action="store_true", help="print each run's journal")
    args = ap.parse_args()
    print(f"{args.runs} runs per variant; two separate sessions each\n")
    print(f"{'variant':<9} {'journal':>8} {'test added':>11} {'passes':>7} {'redid fix':>10} {'re-read':>8} {'s2 calls':>9}   (session 1 wrote the test itself)")
    for variant in args.variants.split(","):
        rows = [run_once(variant, args.model) for _ in range(args.runs)]
        n = len(rows)
        if args.show:
            for r in rows:
                print(r["journal_text"] or "(no journal)")
                print("-----", flush=True)
        print(f"{variant:<9} {sum(r['journal_mentions'] for r in rows):>5}/{n:<2} {sum(r['test_written'] for r in rows):>8}/{n:<2} "
              f"{sum(r['passes'] for r in rows):>4}/{n:<2} {sum(r['redid_fix'] for r in rows):>7}/{n:<2} {sum(r['reread'] for r in rows):>5}/{n:<2} "
              f"{sum(r['calls'] for r in rows) / n:>9.1f}   {sum(r['s1_did_test'] for r in rows)}/{n}", flush=True)


if __name__ == "__main__":
    main()
