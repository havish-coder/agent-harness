"""Lesson 45: does plan mode work with a small model, and does planning first help?

The same six-part request as scripts/todo_lab.py, two ways, on a throwaway copy of the sample project:

    direct   the agent just does it (the harness as it is, todo list and nudges on)
    plan     plan mode: the agent must look, propose with exit_plan_mode, and a scripted user approves ("accept file edits")

What is counted:
    proposed     the agent called exit_plan_mode (rather than writing its plan as an answer, or never planning)
    refused      calls to change something that plan mode refused before approval (the harness, not the model, stopped these)
    changed      files changed before the approval (must be 0: plan mode is the permission layer's job)
    covers       how many of the six parts the plan names (it mentions the file or the thing: cart.py, test, README, CHANGELOG, py.typed, docstring)
    parts        how many parts are in the files at the end

    python scripts/plan_lab.py [--runs 5] [--variants direct,plan] [--model qwen3:4b-instruct] [--show]

Needs Ollama running with the model pulled.
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from todo_lab import REPO, TASK, SaysYes, parts  # noqa: E402

from harness import config  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.providers.fake import committed_copy  # noqa: E402
from harness.security.trust import set_trusted  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tui.plain import PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

COVERS = ["cart.py", "test", "readme", "changelog", "py.typed", "docstring"]


class Scripted(PlainUI):
    """A user who approves the first plan with "accept file edits"."""

    def __init__(self):
        super().__init__()
        self.plans, self.refused = [], 0

    def __call__(self, kind, data):
        if kind == "tool_refused":
            self.refused += 1

    def ask_choice(self, question, options):
        return "a"

    def ask_text(self, question):
        return ""

    def show_plan(self, plan):
        self.plans.append(plan)

    def warn(self, text):
        pass

    def info(self, text):
        pass


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def run_once(variant: str, model: str) -> dict:
    home = Path(tempfile.mkdtemp())
    root = home / "work"
    committed_copy(REPO, "workspace", root)
    if "sum(price for" not in (root / "project" / "shop" / "cart.py").read_text(encoding="utf-8"):
        raise SystemExit("workspace/project/shop/cart.py doesn't have the demo bug any more: git checkout it first")
    config.USER_DIR = home / "user"
    set_trusted(root, config.USER_DIR, True)
    settings = Settings(model=model, audit_log=False, save_chats=False, permission_mode="plan" if variant == "plan" else "bypass",
                        journal="off", auto_memory="off", file_history=False, max_steps=30)
    ui = Scripted()
    try:
        s = Session(settings, Workspace(root), ui, SaysYes())
        before = snapshot(root)
        if variant == "plan":
            # stop at the approval: record what changed before it
            original = s.review_plan
            seen = {}

            def review(plan):
                seen["changed"] = sorted(k for k, v in snapshot(root).items() if before.get(k) != v)
                return original(plan)
            s.agent.tools.get("exit_plan_mode").fn = review
        answer = s.agent.run(TASK)
        calls = [c for m in s.agent.messages for c in m.tool_calls]
        plan = ui.plans[0].lower() if ui.plans else ""
        done = parts(root)
        return {"proposed": bool(ui.plans), "refused": ui.refused, "changed": len(seen.get("changed", [])) if variant == "plan" else 0,
                "covers": sum(word in plan for word in COVERS), "n": sum(done), "done": done, "calls": len(calls),
                "mode": s.permissions.mode, "answer": answer[:100].replace("\n", " "), "plan": ui.plans[0] if ui.plans else ""}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--variants", default="direct,plan")
    ap.add_argument("--model", default="qwen3:4b-instruct")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    print(f"{args.runs} runs per variant, {args.model}; the six-part request\n")
    print(f"{'variant':<8} {'proposed':>9} {'refused':>8} {'changed first':>14} {'plan covers':>12} {'parts done':>11} {'all six':>8} {'tool calls':>11}")
    for variant in args.variants.split(","):
        rows = [run_once(variant, args.model) for _ in range(args.runs)]
        n = len(rows)
        print(f"{variant:<8} {sum(r['proposed'] for r in rows):>7}/{n:<1} {sum(r['refused'] for r in rows) / n:>8.1f} "
              f"{sum(r['changed'] for r in rows):>14} {sum(r['covers'] for r in rows) / n:>12.1f} {sum(r['n'] for r in rows) / n:>11.1f} "
              f"{sum(r['n'] == 6 for r in rows):>6}/{n:<1} {sum(r['calls'] for r in rows) / n:>11.1f}", flush=True)
        if args.show:
            for r in rows:
                print(f"   {r['n']}/6 {''.join('x' if d else '.' for d in r['done'])} mode={r['mode']} proposed={r['proposed']} :: {r['answer']}")
                if r["plan"]:
                    print("      " + r["plan"].replace("\n", "\n      ")[:700])


if __name__ == "__main__":
    main()
