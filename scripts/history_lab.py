"""Lesson 43: does undo put things back exactly, what does it cost, and does the model know after an undo?

    python scripts/history_lab.py roundtrip [--cases 300]     random edits, then rewind: is every file byte-for-byte what it was? (no model)
    python scripts/history_lab.py cost                         what the copies cost in time and disk (no model)
    python scripts/history_lab.py stale [--runs 4]             after /undo, does the model still believe its edit is there? with and
                                                               without the note the harness adds to the next request (needs Ollama)
"""
import argparse
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import config  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.filehistory import FileHistory, digest  # noqa: E402
from harness.messages import ToolCall  # noqa: E402
from harness.providers.fake import ScriptedProvider, committed_copy, text, tool_calls  # noqa: E402
from harness.security.trust import set_trusted  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.tui.plain import PlainUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CONTENTS = [b"", b"x = 1\n", b"line one\r\nline two\r\n", "héllo ✓ 日本語\n".encode(), bytes(range(256)), b"no newline at end",
            b"a\n" * 500, b"\n\n\n"]


def tree(root: Path) -> dict[str, str]:
    """Every file and folder under root: files by content hash, folders as '/'."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        out[rel] = digest(p.read_bytes()) if p.is_file() else "/"
    return out


def scenario(rng: random.Random, work: Path, interfere: bool) -> tuple[bool, str]:
    """A random chat of 1-6 requests, each with 1-5 file writes; rewind to a random request. Returns (ok, what went wrong)."""
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    ws = Workspace(work)
    names = [f"f{i}.{rng.choice(['txt', 'py', 'bin'])}" for i in range(rng.randint(0, 5))]
    for n in names:
        (work / n).write_bytes(rng.choice(CONTENTS))
    (work / "keep").mkdir()
    (work / "keep" / "mine.txt").write_text("not the agent's", encoding="utf-8")
    h = FileHistory(work.parent / (work.name + "-hist"), ws)
    before: list[dict[str, str]] = []                  # the tree as it stood before each request
    for t in range(rng.randint(1, 6)):
        before.append(tree(work))
        h.begin_turn(f"t{t}", f"request {t}")
        for _ in range(rng.randint(1, 5)):
            rel = rng.choice(names + [f"new{rng.randint(0, 3)}.txt", f"d{rng.randint(0, 2)}/sub/n{rng.randint(0, 2)}.txt"])
            p = ws.path(rel)
            old = p.read_bytes() if p.exists() else None
            new = rng.choice(CONTENTS)
            made = []
            for d in (p.parent, *p.parent.parents):
                if d.exists():
                    break
                made.append(d)
            h.record(p, old, new, "write_file", made)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(new)
    k = rng.randrange(len(before))
    user_file = None
    if interfere:                                      # the user edits one of the files the agent changed, afterwards
        touched = [e.path for t in h.all[k:] for e in t.pending() if ws.path(e.path).exists()]
        if touched:
            user_file = rng.choice(touched)
            ws.path(user_file).write_bytes(b"the user's own edit")
    later = [t for t in h.all[k:] if t.pending()]
    out = h.apply(h.plan(later))
    after = tree(work)
    if user_file is None:
        if after != before[k]:
            diff = sorted(set(after.items()) ^ set(before[k].items()))[:4]
            return False, f"tree differs after rewinding to request {k}: {diff}"
        return True, ""
    if (work / user_file).read_bytes() != b"the user's own edit":
        return False, f"the user's edit of {user_file} was overwritten"
    if out.errors:
        return False, f"errors: {out.errors}"
    return True, ""


def roundtrip(cases: int) -> None:
    rng = random.Random(43)
    base = Path(tempfile.mkdtemp())
    try:
        for label, interfere in (("rewind with nobody else touching files", False), ("rewind after the user edited a file", True)):
            bad = []
            started = time.perf_counter()
            for i in range(cases):
                ok, why = scenario(rng, base / "w", interfere)
                if not ok:
                    bad.append((i, why))
            took = time.perf_counter() - started
            print(f"{label}: {cases - len(bad)}/{cases} exact ({took:.1f} s)")
            for i, why in bad[:3]:
                print(f"   case {i}: {why}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(str(base / "w-hist"), ignore_errors=True)


def cost() -> None:
    base = Path(tempfile.mkdtemp())
    try:
        ws = Workspace(base / "w")
        (base / "w").mkdir()
        print(f"{'file size':>10} {'record, ms':>11} {'undo, ms':>9}   (median of 9)")
        for size in (1_000, 100_000, 1_000_000):
            rec, und = [], []
            for i in range(9):
                h = FileHistory(base / f"h{size}-{i}", ws)
                p = ws.path("f.txt")
                old = (f"{i} some line of code\n".encode() * (size // 20 + 1))[:size]    # different content each time: no shortcut from a copy that exists
                p.write_bytes(old)
                h.begin_turn("t", "x")
                new = old.replace(b"some", b"SOME", 1)
                t0 = time.perf_counter()
                h.record(p, old, new, "edit_file")
                t1 = time.perf_counter()
                p.write_bytes(new)
                t2 = time.perf_counter()
                h.apply(h.plan(h.pending_turns()))
                t3 = time.perf_counter()
                rec.append((t1 - t0) * 1000)
                und.append((t3 - t2) * 1000)
            print(f"{size:>10,} {sorted(rec)[4]:>11.1f} {sorted(und)[4]:>9.1f}")
        # disk: 30 edits of a 100 KB file, in one request and in thirty
        for label, per_turn in (("30 edits in one request", 30), ("30 requests, one edit each", 1)):
            h = FileHistory(base / ("disk" + label[:2]), ws)
            p = ws.path("g.txt")
            body = [f"line {i} of the file\n".encode() * 1 for i in range(5000)]
            p.write_bytes(b"".join(body))
            n = 0
            for t in range(30 // per_turn):
                h.begin_turn(f"t{t}", "x")
                for _ in range(per_turn):
                    n += 1
                    old = p.read_bytes()
                    body[n] = f"edited {n}\n".encode()
                    new = b"".join(body)
                    h.record(p, old, new, "edit_file")
                    p.write_bytes(new)
            kb = h.store_bytes() / 1000
            print(f"{label}: {kb:,.0f} KB of copies for a {len(p.read_bytes()) / 1000:,.0f} KB file ({len(list((h.base / 'blobs').glob('*/*')))} copies)")
    finally:
        shutil.rmtree(base, ignore_errors=True)


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


def stale_once(note: bool, model: str) -> dict:
    home = Path(tempfile.mkdtemp())
    root = home / "work"
    committed_copy(REPO, "workspace", root)
    if "sum(price for" not in (root / "project" / "shop" / "cart.py").read_text(encoding="utf-8"):
        raise SystemExit("workspace/project/shop/cart.py doesn't have the demo bug any more: git checkout it first")
    config.USER_DIR = home / "user"
    set_trusted(root, config.USER_DIR, True)
    settings = Settings(model=model, audit_log=False, save_chats=False, permission_mode="bypass", journal="off", auto_memory="off")
    try:
        s = Session(settings, Workspace(root), Quiet(), SaysYes())
        real = s.agent.provider
        cart = "project/shop/cart.py"
        # the first request is scripted, so the edit always happens: what is measured is what the model does *after* the undo
        s.agent.provider = ScriptedProvider([
            tool_calls(ToolCall("1", "read_file", {"path": cart})),
            tool_calls(ToolCall("2", "edit_file", {"path": cart, "old_string": "sum(price for _, price, qty", "new_string": "sum(price * qty for _, price, qty"})),
            text("Fixed: subtotal() now multiplies each price by its quantity.")])
        s.agent.run("Fix the subtotal bug in project/shop/cart.py: it ignores the quantity.")
        fixed = "price * qty" in (root / "project" / "shop" / "cart.py").read_text(encoding="utf-8")
        s.undo()
        undone = "sum(price for" in (root / "project" / "shop" / "cart.py").read_text(encoding="utf-8")
        if not note:
            s.agent.pending_notes.clear()               # the model is not told: the conversation still says its edit is there
        s.agent.provider = real
        reply = s.agent.run("Quote the exact line in subtotal() as it is in the file right now. Answer with that line only.")
        calls = [c.name for m in s.agent.messages[-6:] for c in m.tool_calls]
        return {"fixed": fixed, "undone": undone, "reread": "read_file" in calls or "grep" in calls,
                "believes_edit": "price * qty" in reply and "sum(price for" not in reply,
                "correct": "sum(price for" in reply and "price * qty" not in reply, "reply": reply[:100].replace("\n", " ")}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def stale(runs: int, model: str) -> None:
    print(f"{runs} runs per row, {model}: a scripted fix, /undo, then ask the model what the line is now\n")
    print(f"{'the harness':<28} {'undone':>13} {'re-read':>8} {'answered with the stale edit':>29} {'answered correctly':>19}")
    for label, note in (("adds the note", True), ("says nothing", False)):
        rows = [stale_once(note, model) for _ in range(runs)]
        valid = [r for r in rows if r["fixed"] and r["undone"]]
        n = len(valid)
        print(f"{label:<28} {n:>10}/{runs:<2} {sum(r['reread'] for r in valid):>5}/{n:<2} "
              f"{sum(r['believes_edit'] for r in valid):>26}/{n:<2} {sum(r['correct'] for r in valid):>16}/{n:<2}", flush=True)
        for r in valid[:2]:
            print(f"     e.g. {r['reply']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["roundtrip", "cost", "stale"])
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--model", default="qwen3:4b-instruct")
    args = ap.parse_args()
    {"roundtrip": lambda: roundtrip(args.cases), "cost": cost, "stale": lambda: stale(args.runs, args.model)}[args.task]()


if __name__ == "__main__":
    main()
