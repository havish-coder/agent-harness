"""Lesson 44: does a todo list help a small model finish a task with several parts?

One request with six parts, on a throwaway copy of the sample project. Each part can be checked in the files afterwards.

    none     no todo tool at all
    tool     the todo_write tool, described only by its own description
    rule     the tool, and a sentence in the system prompt saying when to use it
    nudge    the tool, the sentence, and the harness sends the model back (at most twice) when it tries to finish with items still open
    seed     all of that, and the harness writes the list itself from the request's numbered items

    python scripts/todo_lab.py [--runs 5] [--variants none,list,nudge] [--model qwen3:4b-instruct] [--show]

Needs Ollama running with the model pulled.
"""
import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import config  # noqa: E402
from harness import session as session_module  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.providers.fake import committed_copy  # noqa: E402
from harness.security.trust import set_trusted  # noqa: E402
from harness.session import TODO_RULE as RULE  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tui.plain import PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TASK = """Please do all six of these in the project in project/:
1. Fix the subtotal bug in project/shop/cart.py: it ignores the quantity.
2. Add a test in project/tests/test_cart.py that adding an item with quantity 0 raises ValueError.
3. Add a "## Usage" section to project/README.md with a short example of using Cart.
4. Create project/CHANGELOG.md with a line saying the subtotal bug was fixed.
5. Create project/shop/py.typed containing the single word typed.
6. Add a docstring to the total method of project/shop/cart.py."""


def parts(root: Path) -> list[bool]:
    """Which of the six parts are in the files."""
    p = root / "project"

    def text(name: str) -> str:
        f = p / name
        return f.read_text(encoding="utf-8", errors="replace") if f.exists() else ""

    cart = re.sub(r"\s+", "", text("shop/cart.py"))
    total = re.search(r"deftotal\(self[^)]*\)(?:->\w+)?:(?P<body>.{0,3})", cart)
    return [
        "price*qty" in cart or "qty*price" in cart,
        "ValueError" in text("tests/test_cart.py"),
        "usage" in text("README.md").lower() and "cart" in text("README.md").lower().split("usage", 1)[-1],
        "subtotal" in text("CHANGELOG.md").lower(),
        "typed" in text("shop/py.typed").lower(),
        bool(total) and total.group("body").startswith(('"""', "'''")),
    ]


class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.nudges = 0

    def __call__(self, kind, data):
        if kind == "nudge":
            self.nudges += 1

    def warn(self, text):
        pass

    def info(self, text):
        pass


class SaysYes:
    pause = None

    def __call__(self, call, tool, decision=None):
        return True


def run_once(variant: str, model: str) -> dict:
    home = Path(tempfile.mkdtemp())
    root = home / "work"
    committed_copy(REPO, "workspace", root)
    if "sum(price for" not in (root / "project" / "shop" / "cart.py").read_text(encoding="utf-8"):
        raise SystemExit("workspace/project/shop/cart.py doesn't have the demo bug any more: git checkout it first")
    config.USER_DIR = home / "user"
    set_trusted(root, config.USER_DIR, True)
    settings = Settings(model=model, audit_log=False, save_chats=False, permission_mode="bypass", journal="off", auto_memory="off",
                        file_history=False, max_steps=30, todo=variant != "none")
    ui = Quiet()
    try:
        if variant == "tool":
            session_module.TODO_RULE = ""                  # no sentence in the prompt
        s = Session(settings, Workspace(root), ui, SaysYes())
        session_module.TODO_RULE = RULE
        if variant in ("tool", "rule"):
            s.agent.finish_check = None
        if variant != "seed":
            s.agent.on_request = None                    # the harness doesn't write the list from the numbered request
        answer = s.agent.run(TASK)
        calls = [c for m in s.agent.messages for c in m.tool_calls]
        done = parts(root)
        return {"done": done, "n": sum(done), "calls": len(calls), "todo_calls": sum(c.name == "todo_write" for c in calls),
                "nudges": ui.nudges, "stop": s.agent.stop_reason, "answer": answer[:120].replace("\n", " "),
                "list": s.todos.text()}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--variants", default="none,tool,rule,nudge,seed")
    ap.add_argument("--model", default="qwen3:4b-instruct")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    print(f"{args.runs} runs per variant, {args.model}; a request with six parts\n")
    print(f"{'variant':<8} {'parts done (mean)':>18} {'all six':>8} {'tool calls':>11} {'todo_write':>11} {'nudges':>7} {'hit max steps':>14}")
    for variant in args.variants.split(","):
        rows = [run_once(variant, args.model) for _ in range(args.runs)]
        n = len(rows)
        print(f"{variant:<8} {sum(r['n'] for r in rows) / n:>18.1f} {sum(r['n'] == 6 for r in rows):>6}/{n:<2} "
              f"{sum(r['calls'] for r in rows) / n:>11.1f} {sum(r['todo_calls'] for r in rows) / n:>11.1f} "
              f"{sum(r['nudges'] for r in rows) / n:>7.1f} {sum(r['stop'] == 'max_steps' for r in rows):>12}/{n}", flush=True)
        if args.show:
            for r in rows:
                print(f"   {r['n']}/6 {''.join('x' if d else '.' for d in r['done'])} stop={r['stop']} :: {r['answer']}")
                if r["list"]:
                    print("      " + r["list"].replace("\n", "\n      "))


if __name__ == "__main__":
    main()
