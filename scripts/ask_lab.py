"""Lesson 46: does a small model ask when it should, and only then?

Three kinds of request, two of each, on a throwaway copy of the sample project:

    unclear      the answer changes what gets built ("add a coupon feature": a percentage? a fixed amount? one use?)       -> should ask
    clear        nothing to ask ("fix the subtotal bug: it ignores the quantity")                                         -> should not
    findable     it looks like a question but the files answer it ("add a test for total in the existing test file")     -> should look, not ask

A scripted user answers every question ("Use your best judgment: ..."), so each run finishes.

    tool     the ask_user tool, described only by its own description
    rule     the tool, and one sentence in the system prompt saying when to ask

    python scripts/ask_lab.py [--runs 4] [--variants tool,rule] [--model qwen3:4b-instruct] [--show]

Needs Ollama running with the model pulled.
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from todo_lab import REPO, SaysYes  # noqa: E402

from harness import config  # noqa: E402
from harness import session as session_module  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.providers.fake import committed_copy  # noqa: E402
from harness.security.trust import set_trusted  # noqa: E402
from harness.session import ASK_RULE as RULE  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tui.plain import PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

TASKS = {
    "unclear": ["Add a coupon feature to the shopping cart in project/.", "Make the cart's prices round the way I want."],
    "clear": ["Fix the subtotal bug in project/shop/cart.py: it ignores the quantity.", "Create project/shop/py.typed containing the single word typed."],
    "findable": ["Add a test for the total method of Cart, in the project's existing test file.", "Which function in project/ applies the tax? Answer from the code."],
}
EDITS = ("edit_file", "write_file")


class User(PlainUI):
    """Answers every question the same way, and keeps what was asked."""

    def __init__(self):
        super().__init__()
        self.asked = []

    def __call__(self, kind, data):
        pass

    def ask_choice(self, question, options):
        self.asked.append(question)
        return "1" if "1" in options else ""

    def ask_text(self, question):
        self.asked.append(question)
        return "Use your best judgment: the simplest sensible choice."

    def warn(self, text):
        pass

    def info(self, text):
        pass


def run_once(variant: str, task: str, model: str) -> dict:
    home = Path(tempfile.mkdtemp())
    root = home / "work"
    committed_copy(REPO, "workspace", root)
    config.USER_DIR = home / "user"
    set_trusted(root, config.USER_DIR, True)
    settings = Settings(model=model, audit_log=False, save_chats=False, permission_mode="bypass", journal="off", auto_memory="off",
                        file_history=False, max_steps=14, todo=False)
    ui = User()
    try:
        if variant == "tool":
            session_module.ASK_RULE = ""
        s = Session(settings, Workspace(root), ui, SaysYes())
        session_module.ASK_RULE = RULE
        s.agent.run(task)
        calls = [c for m in s.agent.messages for c in m.tool_calls]
        order = [c.name for c in calls]
        first_ask = order.index("ask_user") if "ask_user" in order else None
        first_edit = next((i for i, n in enumerate(order) if n in EDITS), None)
        return {"asked": len(ui.asked), "any": bool(ui.asked), "first": ui.asked[0][:110].replace("\n", " ") if ui.asked else "",
                "before_edit": first_ask is not None and (first_edit is None or first_ask < first_edit), "calls": len(calls)}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--variants", default="tool,rule")
    ap.add_argument("--model", default="qwen3:4b-instruct")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    print(f"{args.runs} runs per request, 2 requests per kind, {args.model}\n")
    print(f"{'variant':<8} {'kind':<10} {'asked':>8} {'asked first':>12} {'questions (mean)':>17} {'tool calls':>11}")
    for variant in args.variants.split(","):
        for kind, tasks in TASKS.items():
            rows = [(t, run_once(variant, t, args.model)) for t in tasks for _ in range(args.runs)]
            n = len(rows)
            print(f"{variant:<8} {kind:<10} {sum(r['any'] for _, r in rows):>5}/{n:<2} {sum(r['before_edit'] for _, r in rows):>9}/{n:<2} "
                  f"{sum(r['asked'] for _, r in rows) / n:>17.1f} {sum(r['calls'] for _, r in rows) / n:>11.1f}", flush=True)
            if args.show:
                for t, r in rows:
                    if r["first"]:
                        print(f"     {t[:45]!r}: {r['first']}")


if __name__ == "__main__":
    main()
