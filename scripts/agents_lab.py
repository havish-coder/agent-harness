"""Lesson 47: what does a sub-agent do for the parent's context window, and will a small model use one?

A synthetic package `inventory/` of 14 modules (about 100 lines each, so reading them all would take roughly 17,000 tokens against a window of 8,192) with six
facts planted, each in a different module. Three experiments:

    context   (no model) the parent's conversation after exploring 8 modules: reading them itself, or through `delegate`
    answers   a real model answers four questions about the package three ways:
                inline   no sub-agents: the agent reads for itself
                rule     `delegate` is offered, and a sentence in the system prompt says when to use it
                forced   the harness makes the first move (the question is delegated for it); the model only writes the final answer
    ...       for each: right answers, tokens the parent's conversation holds at the end, tool calls the parent made, delegations, tokens used in all

    python scripts/agents_lab.py context
    python scripts/agents_lab.py answers [--runs 3] [--variants inline,rule,forced] [--model qwen3:4b-instruct]
"""
import argparse
import random
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from todo_lab import SaysYes  # noqa: E402

from harness import config  # noqa: E402
from harness import session as session_module  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.context.tokens import estimate_tokens  # noqa: E402
from harness.messages import ToolCall  # noqa: E402
from harness.providers.fake import ScriptedProvider, text, tool_calls  # noqa: E402
from harness.security.trust import set_trusted  # noqa: E402
from harness.session import SUBAGENT_RULE as RULE  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tui.plain import PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

PLANTED = {
    "net.py": 'RETRY_LIMIT = 7  # how many times a request is repeated before giving up\n',
    "text_utils.py": 'def slugify(title):\n    """Lower-case a title and join its words with dashes."""\n    return "-".join(title.lower().split())\n',
    "warehouse.py": ('class Warehouse:\n    """Stock on hand for one site."""\n\n    def reorder_point(self, daily_demand):\n'
                     '        """Stock level at which to order more."""\n        return 3 * daily_demand\n'),
    "money.py": 'DEFAULT_CURRENCY = "EUR"\n',
    "logging_setup.py": 'LOG_LEVEL = "WARNING"  # the package logs warnings and worse unless told otherwise\n',
    "sku.py": 'def parse_sku(code):\n    """Split a SKU like AB-1234 into its parts."""\n    if "-" not in code:\n        raise ValueError("bad sku")\n    return code.split("-", 1)\n',
}
FILLERS = ["shipping", "pricing", "reports", "users", "orders", "audit", "cache", "settings"]
WORDS = ["total", "count", "price", "weight", "stock", "batch", "label", "route", "limit", "score", "range", "level", "share", "queue", "index"]
QUESTIONS = [
    ("What is the value of RETRY_LIMIT in the inventory package? Answer with the number.", ["7"]),
    ("Which file in the inventory package defines the function slugify? Answer with the file name.", ["text_utils"]),
    ("What does Warehouse.reorder_point return in the inventory package? Answer with the expression.", ["daily_demand"]),
    ("What error message does parse_sku raise in the inventory package for a bad SKU? Answer with the message.", ["bad sku"]),
]


def make_corpus(root: Path) -> list[Path]:
    """Write inventory/ with the planted facts and filler modules, the same every time."""
    rng = random.Random(47)
    folder = root / "inventory"
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text('"""Inventory tools."""\n', encoding="utf-8")
    files = []
    names = list(PLANTED) + [f"{n}.py" for n in FILLERS]
    for name in names:
        body = [f'"""{name[:-3].replace("_", " ").title()}."""', ""]
        if name in PLANTED:
            body += PLANTED[name].splitlines() + [""]
        for i in range(14):
            a, b, c = rng.sample(WORDS, 3)
            body += [f"def {a}_{b}_{i}({a}, {b}=1):", f'    """Work out the {a} for a {b}, adjusted by {c} number {i}."""',
                     f"    result = {a} * {b}", f"    for step in range({i + 2}):", f"        result += step * {rng.randint(2, 9)}",
                     f"    if result > {rng.randint(100, 999)}:", f"        result = result % {rng.randint(11, 97)}", "    return result", ""]
        path = folder / name
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        files.append(path)
    return files


class Quiet(PlainUI):
    def __call__(self, kind, data):
        pass

    def warn(self, text_):
        pass

    def info(self, text_):
        pass

    def ask_choice(self, question, options):
        return ""

    def ask_text(self, question):
        return ""


def new_session(root: Path, **settings) -> Session:
    config.USER_DIR = root.parent / "user"
    set_trusted(root, config.USER_DIR, True)
    base = dict(audit_log=False, save_chats=False, permission_mode="bypass", journal="off", auto_memory="off", file_history=False, todo=False, max_steps=14)
    return Session(Settings(**(base | settings)), Workspace(root), Quiet(), SaysYes())


def context() -> None:
    home = Path(tempfile.mkdtemp())
    try:
        root = home / "work"
        files = make_corpus(root)[:8]
        reads = [tool_calls(ToolCall(f"r{i}", "read_file", {"path": f"inventory/{p.name}"})) for i, p in enumerate(files)]
        inline = new_session(root, microcompact=False, auto_compact=False, context_window=65536)
        inline.agent.provider = ScriptedProvider([*reads, text("Reviewed all eight modules.")])
        inline.agent.run("Review the inventory package.")
        inline_tokens = inline.estimate_context()

        delegated = new_session(root, microcompact=False, auto_compact=False, context_window=65536)
        delegated.provider.inner = ScriptedProvider([tool_calls(ToolCall("d", "delegate", {"agent": "explore", "task": "Review the inventory package."})),
                                                     *[tool_calls(ToolCall(f"s{i}", "read_file", {"path": f"inventory/{p.name}"})) for i, p in enumerate(files)],
                                                     text("The package has 8 modules of small numeric helpers; none looked wrong."), text("Reviewed.")])
        delegated.agent.run("Review the inventory package.")
        delegated_tokens = delegated.estimate_context()
        read = sum(estimate_tokens(p.read_text(encoding="utf-8")) for p in files)
        print(f"8 modules, {read:,} tokens of source (the model's whole window is 8,192)")
        print(f"  the parent's conversation after reading them itself:        ~{inline_tokens:,} tokens")
        print(f"  the parent's conversation after delegating the same job:    ~{delegated_tokens:,} tokens")
        print("  (the window of this run was widened to 65,536 so that nothing was cleared in either case)")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def run_once(variant: str, question: str, model: str) -> dict:
    home = Path(tempfile.mkdtemp())
    try:
        root = home / "work"
        make_corpus(root)
        session_module.SUBAGENT_RULE = RULE if variant == "rule" else ""
        s = new_session(root, model=model, subagents=variant != "inline")
        session_module.SUBAGENT_RULE = RULE
        if variant == "forced":
            # the first move is made for the model: the question goes to the explorer, whose reports the real model then only has to relay
            real = s.agent.provider
            s.agent.provider = ScriptedProvider([tool_calls(ToolCall("d", "delegate", {"agent": "explore", "task": question}))])
            s.agent.provider = _Chain(s.agent.provider, real)
        answer = s.agent.run(question)
        calls = [c for m in s.agent.messages for c in m.tool_calls]
        return {"answer": answer, "calls": len(calls), "delegated": sum(c.name == "delegate" for c in calls), "tokens": s.limits.tokens,
                "context": s.estimate_context(), "stop": s.agent.stop_reason}
    finally:
        shutil.rmtree(home, ignore_errors=True)


class _Chain:
    """Answers the first request from `first` (a scripted delegation) and every later one from `then` (the real model)."""

    def __init__(self, first, then):
        self.first, self.then, self.used = first, then, False
        self.model = getattr(then, "model", "x")

    def chat(self, messages, tools):
        if not self.used:
            self.used = True
            return self.first.chat(messages, tools)
        return self.then.chat(messages, tools)

    def __getattr__(self, name):
        return getattr(self.then, name)


def answers(runs: int, variants: list[str], model: str) -> None:
    print(f"{runs} runs per question, {len(QUESTIONS)} questions, {model}\n")
    print(f"{'variant':<8} {'right':>7} {'parent context':>15} {'parent calls':>13} {'delegated':>10} {'tokens used':>12} {'stopped early':>14}")
    for variant in variants:
        rows = []
        for question, expected in QUESTIONS:
            for _ in range(runs):
                r = run_once(variant, question, model)
                r["right"] = any(e.lower() in r["answer"].lower() for e in expected)
                rows.append(r)
        n = len(rows)
        print(f"{variant:<8} {sum(r['right'] for r in rows):>4}/{n:<2} {sum(r['context'] for r in rows) / n:>15,.0f} {sum(r['calls'] for r in rows) / n:>13.1f} "
              f"{sum(r['delegated'] for r in rows):>6}/{n:<3} {sum(r['tokens'] for r in rows) / n:>12,.0f} {sum(r['stop'] != 'completed' for r in rows):>12}/{n}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["context", "answers"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--variants", default="inline,rule,forced")
    ap.add_argument("--model", default="qwen3:4b-instruct")
    args = ap.parse_args()
    if args.task == "context":
        context()
    else:
        answers(args.runs, args.variants.split(","), args.model)


if __name__ == "__main__":
    main()
