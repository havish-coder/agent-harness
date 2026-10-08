"""Lesson 49: where should instructions live: always in the prompt, or loaded when needed?

The job: write a commit message for a small diff, in a strict house format (the skill):

    first line   type(scope): summary   type is one of feat, fix, docs, refactor, test; summary lower-case, no full stop; the whole line at most 50 characters
    then         a blank line
    then         two or three bullet lines, each starting "- "
    last line    Refs: none

A message either follows every rule or it doesn't. Four ways of giving the model the rule:

    none      no skill: the model's own idea of a commit message
    memory    the text is in the project's HARNESS.md, so it is in every request's prompt (the cost is paid every time)
    skill     the prompt lists the skill in one line; the model may load it with use_skill
    command   the user starts it: `/commit-message ...` loads the skill and sends the request (nothing for the model to decide)

    python scripts/skills_lab.py [--runs 4] [--variants none,memory,skill,command] [--model qwen3:4b-instruct]
"""
import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from todo_lab import SaysYes  # noqa: E402

from harness import config  # noqa: E402
from harness.commands import load_commands  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.context.tokens import estimate_tokens  # noqa: E402
from harness.security.trust import set_trusted  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tui.plain import PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

SKILL = """Write the commit message in this project's format. Follow every rule.
- First line: `type(scope): summary`. type is one of feat, fix, docs, refactor, test. scope is one lower-case word for the part of the code. summary is lower-case, imperative, no full stop. The whole first line is at most 50 characters.
- Then a blank line.
- Then two or three bullet lines, each starting with "- ", saying what changed and why.
- The last line is exactly: Refs: none
Reply with the commit message and nothing else."""
DIFFS = [
    "--- a/shop/cart.py\n+++ b/shop/cart.py\n@@ -14,3 +14,3 @@\n     def subtotal(self) -> float:\n-        return sum(price for _, price, qty in self.items)\n+        return sum(price * qty for _, price, qty in self.items)",
    "--- a/README.md\n+++ b/README.md\n@@ -8,0 +9,6 @@\n+## Usage\n+\n+    cart = Cart()\n+    cart.add(\"pen\", 2.0, quantity=3)\n+    cart.subtotal()  # 6.0",
    "--- a/tests/test_cart.py\n+++ b/tests/test_cart.py\n@@ -12,0 +13,6 @@\n+def test_zero_quantity_is_refused():\n+    cart = Cart()\n+    with pytest.raises(ValueError):\n+        cart.add(\"pen\", 2.0, quantity=0)",
]
TYPES = ("feat", "fix", "docs", "refactor", "test")
FIRST = re.compile(rf"^({'|'.join(TYPES)})\([a-z][a-z-]*\): [a-z][^\n]*[^.\n]$")


def follows(message: str) -> bool:
    lines = message.strip().splitlines()
    if len(lines) < 5 or not FIRST.match(lines[0]) or len(lines[0]) > 50 or lines[1].strip() or lines[-1].strip() != "Refs: none":
        return False
    bullets = [b for b in lines[2:-1] if b.strip()]          # a blank line before the last line is fine
    return 2 <= len(bullets) <= 3 and all(b.startswith("- ") for b in bullets)


class Quiet(PlainUI):
    def __call__(self, kind, data):
        pass

    def warn(self, text):
        pass

    def info(self, text):
        pass


def run_once(variant: str, diff: str, model: str) -> dict:
    home = Path(tempfile.mkdtemp())
    try:
        root = home / "work"
        root.mkdir()
        config.USER_DIR = home / "user"
        import harness.commands as commands_module
        commands_module.USER_DIR = config.USER_DIR
        set_trusted(root, config.USER_DIR, True)
        if variant == "memory":
            (root / "HARNESS.md").write_text("When asked for a commit message:\n" + SKILL + "\n", encoding="utf-8")
        elif variant in ("skill", "command"):
            folder = config.USER_DIR / "skills" / "commit-message"
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text("---\ndescription: Write a commit message in this project's format\n---\n" + SKILL + "\n", encoding="utf-8")
        settings = Settings(model=model, audit_log=False, save_chats=False, permission_mode="bypass", journal="off", auto_memory="off", file_history=False,
                            todo=False, subagents=False, background_tasks=False, max_steps=6)
        s = Session(settings, Workspace(root), Quiet(), SaysYes())
        request = f"Write the commit message for this change:\n\n{diff}"
        if variant == "command":
            command, args = load_commands(root).parse(f"/commit-message {request}")
            request = command.expand(args)
        answer = s.agent.run(request)
        calls = [c.name for m in s.agent.messages for c in m.tool_calls]
        return {"ok": follows(answer), "prompt": estimate_tokens(s.prompt.text), "tokens": s.limits.tokens, "used": "use_skill" in calls, "answer": answer}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--variants", default="none,memory,skill,command")
    ap.add_argument("--model", default="qwen3:4b-instruct")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    print(f"{args.runs} runs per diff, {len(DIFFS)} diffs, {args.model}\n")
    print(f"{'variant':<8} {'follows the format':>19} {'loaded the skill':>17} {'system prompt':>14} {'tokens used':>12}")
    for variant in args.variants.split(","):
        rows = [run_once(variant, d, args.model) for d in DIFFS for _ in range(args.runs)]
        n = len(rows)
        print(f"{variant:<8} {sum(r['ok'] for r in rows):>16}/{n:<2} {sum(r['used'] for r in rows):>14}/{n:<2} {sum(r['prompt'] for r in rows) / n:>12.0f}t "
              f"{sum(r['tokens'] for r in rows) / n:>12.0f}", flush=True)
        if args.show:
            for r in rows[:2]:
                print("   ---\n   " + r["answer"].strip().replace("\n", "\n   "))


if __name__ == "__main__":
    main()
