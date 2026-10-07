"""Lesson 43: file history, so what the agent changed in your files can be undone.

The edit tools (`edit_file`, `write_file`) save a file's previous content **just before** they write the new one. Each save
belongs to the *request* (turn) the user had made, so "undo" can mean "put back what the last request changed", and "rewind" can
mean "go back to before request 3".

It lives in your user folder, next to the saved chats, never in the workspace:

    <project folder>/history/blobs/<aa>/<sha256>       a file as it was before a change; immutable, shared by every chat
    <project folder>/history/<chat id>.jsonl           one chat's log of what happened, append-only

    {"t":"turn","id":"3fa9c2d1","at":...,"prompt":"Fix the subtotal bug ..."}                    a request began
    {"t":"change","turn":...,"path":"shop/cart.py","first":true,"before":"<sha>"|null,"after":"<sha>","plus":1,"minus":1,
     "tool":"edit_file","dirs":[]}                                                                 a file was written (before null: it was new)
    {"t":"command","turn":...,"text":"python make.py"}                                             a shell command that may have changed files
    {"t":"reverted","turn":...,"paths":[...]}                                                      files were put back
    {"t":"dropped","turns":[...]}                                                                the conversation went back before these requests

Three rules make it safe to rely on:

* **The copy is made before the write, and the log line before the write too.** A crash can leave a log line for a write that never
  happened (undo then finds the file already as it was), never a write with no way back.
* **Undo never overwrites work it didn't make.** Each change records the hash of what the agent wrote; undo only puts a file back if it
  still has that content. A file you have edited since is a *conflict*: it is skipped and reported, and only `force` overwrites it (and
  then keeps your version too).
* **The model has no undo.** Restoring is the user's command, so a page the agent read can't ask for it, and the path rules still apply.

Not covered, said plainly: files changed by `run_shell` (the harness can't know which), and anything outside the workspace's folders.
A turn that ran such a command says so when you undo it.
"""
import difflib
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from harness.chats import now, private
from harness.security.redact import redacted
from harness.workspace import Workspace

SEPARATORS = (",", ":")
MAX_FILE_BYTES = 2_000_000          # the largest file a copy is kept of (the edit tools refuse bigger ones anyway)
MAX_STORE_BYTES = 400_000_000       # all the copies of one project: past this nothing more is kept, and the user is told
PROMPT_CHARS = 80
DIFF_LINES = 4_000                  # past this many lines a change is counted roughly, because a line diff gets slow
FOLDER = "is a folder now"
BLOB_GRACE = 3_600                 # seconds: a copy newer than this is never collected, a log line may be on its way


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_name(text: str, limit: int = 120) -> str:
    """A file name or command for a message to the user or the model: one line, no control characters, not too long."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def line_counts(before: bytes | None, after: bytes) -> tuple[int, int]:
    """(lines added, lines removed) going from `before` to `after`. Roughly, for files of thousands of lines."""
    new = after.decode("utf-8", errors="replace").splitlines()
    old = before.decode("utf-8", errors="replace").splitlines() if before is not None else []
    if len(old) + len(new) > DIFF_LINES:
        return len(new), len(old)
    plus = minus = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            minus += i2 - i1
        if tag in ("replace", "insert"):
            plus += j2 - j1
    return plus, minus


# --- what the log says ---------------------------------------------------------------------------

@dataclass
class Edit:
    """What the changes of one request did to one file."""
    path: str
    before: str | None                      # hash of the content before the request's first change (None: it did not exist)
    after: str | None                       # hash of what the last change wrote
    plus: int = 0
    minus: int = 0
    tools: list[str] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)       # folders the first change had to create
    reverted: bool = False

    @property
    def new(self) -> bool:
        return self.before is None


@dataclass
class Turn:
    """One request the user made, and the files it changed."""
    id: str
    prompt: str
    at: str = ""
    edits: dict[str, Edit] = field(default_factory=dict)
    commands: list[str] = field(default_factory=list)
    dropped: bool = False                   # the conversation was rewound to before this request

    def pending(self) -> list[Edit]:
        return [e for e in self.edits.values() if not e.reverted]


@dataclass
class Step:
    """One file, as undo would find it."""
    path: str
    action: str              # "restore", "delete", "same" (already as it was), "conflict", "refused"
    target: str | None       # the hash to put back (None: the file didn't exist)
    detail: str = ""
    edit: Edit | None = None
    dirs: list[str] = field(default_factory=list)
    plus: int = 0
    minus: int = 0


@dataclass
class Plan:
    turns: list[Turn]
    steps: list[Step]

    @property
    def commands(self) -> list[str]:
        return [c for t in self.turns for c in t.commands]

    def conflicts(self) -> list[Step]:
        return [s for s in self.steps if s.action == "conflict"]


@dataclass
class Outcome:
    restored: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    same: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)       # (path, why): changed since, or refused
    errors: list[tuple[str, str]] = field(default_factory=list)
    kept: dict[str, str] = field(default_factory=dict)                 # path -> hash of your version, saved before a forced undo
    commands: list[str] = field(default_factory=list)

    @property
    def changed(self) -> list[str]:
        return self.restored + self.deleted


def parse_log(text: str) -> list[Turn]:
    """Rebuild what happened from a chat's history log. Unreadable lines are skipped."""
    turns: dict[str, Turn] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            kind = e["t"]
            if kind == "turn":
                turns[e["id"]] = Turn(e["id"], e.get("prompt", ""), e.get("at", ""))
            elif kind == "change":
                turn = turns[e["turn"]]
                edit = turn.edits.get(e["path"])
                if edit is None or e.get("first"):
                    edit = turn.edits[e["path"]] = Edit(e["path"], e.get("before"), e.get("after"), dirs=list(e.get("dirs", [])))
                else:
                    edit.after = e.get("after")
                edit.plus += int(e.get("plus", 0))
                edit.minus += int(e.get("minus", 0))
                if e.get("tool") and e["tool"] not in edit.tools:
                    edit.tools.append(e["tool"])
            elif kind == "command":
                turns[e["turn"]].commands.append(e["text"])
            elif kind == "reverted":
                for path in e["paths"]:
                    if path in turns[e["turn"]].edits:
                        turns[e["turn"]].edits[path].reverted = True
            elif kind == "dropped":
                for id in e["turns"]:
                    if id in turns:
                        turns[id].dropped = True
        except (ValueError, KeyError, TypeError):
            continue
    return list(turns.values())


# --- the history of one chat ---------------------------------------------------------------------

class FileHistory:
    """The copies and the log for one chat. Without a log file (`bind` not called) it works in memory, which is what tests and scripts want."""

    def __init__(self, base: Path | str, ws: Workspace, on_problem=None):
        self.base = Path(base)
        self.ws = ws
        self.on_problem = on_problem            # called with a sentence when something can't be kept: the edit still goes ahead
        self.chat_id: str | None = None
        self.log: Path | None = None
        self.all: list[Turn] = []
        self.turn: Turn | None = None            # the request being worked on
        self.problems: list[str] = []
        self._stored: int | None = None          # bytes in the copies folder, counted on first use

    # -- the log ------------------------------------------------------------------------------
    def bind(self, chat_id: str) -> None:
        """Use this chat's log: read what it already holds (a resumed chat), and add to it from now on."""
        self.chat_id, self.log = chat_id, self.base / f"{chat_id}.jsonl"
        self.all = parse_log(self.log.read_text(encoding="utf-8", errors="replace")) if self.log.exists() else self.all
        self.turn = None

    def unbind(self) -> None:
        """A new chat: forget this one's history (it stays on disk)."""
        self.chat_id = self.log = self.turn = None
        self.all = []

    def fork_to(self, chat_id: str) -> None:
        """The conversation was copied into a new chat: it starts with the same history, and the original keeps its own."""
        old = self.log
        self.chat_id, self.log = chat_id, self.base / f"{chat_id}.jsonl"
        if old is not None and old.exists():
            self.base.mkdir(parents=True, exist_ok=True)
            self.log.write_text(old.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            private(self.log, 0o600)

    def append(self, entry: dict) -> None:
        if self.log is None:
            return
        try:
            new = not self.log.exists()
            self.base.mkdir(parents=True, exist_ok=True)
            with self.log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, separators=SEPARATORS) + "\n")
            if new:
                private(self.log, 0o600)
        except OSError as e:
            self.problem(f"the file history can't be written ({e}): changes from now on may not be undoable")

    def problem(self, text: str) -> None:
        if text not in self.problems:
            self.problems.append(text)
            if self.on_problem:
                self.on_problem(text)

    # -- recording ----------------------------------------------------------------------------
    def begin_turn(self, id: str, prompt: str) -> Turn:
        """A request began: the changes that follow belong to it."""
        turn = next((t for t in self.all if t.id == id), None)
        if turn is None:
            turn = Turn(id, redacted(" ".join(prompt.split()))[:PROMPT_CHARS], now())
            self.all.append(turn)
            self.append({"t": "turn", "id": id, "at": turn.at, "prompt": turn.prompt})
        self.turn = turn
        return turn

    def blob(self, sha: str) -> Path:
        return self.base / "blobs" / sha[:2] / sha

    def keep(self, data: bytes) -> str:
        """Store a copy (once: the name is its hash) and return the hash."""
        sha = digest(data)
        path = self.blob(sha)
        if not path.exists():
            if self._stored is None:
                self._stored = self.store_bytes()
            if self._stored + len(data) > MAX_STORE_BYTES:
                raise OSError(f"the file history is full ({self._stored // 1_000_000} MB); /undo and /rewind can't keep more copies")
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            private(path, 0o600)
            self._stored += len(data)
        return sha

    def record(self, p: Path, before: bytes | None, after: bytes, tool: str, created_dirs=()) -> bool:
        """Called by an edit tool just before it writes `after` over `before` (None: the file is new). Keeps the old content.

        It never raises: if the copy can't be kept (too big, disk full) the edit still happens, and the user is told once that it
        can't be undone. A tool that has to ask permission to *change* things shouldn't also be stopped by a full history disk."""
        name = self.ws.display(p)
        turn = self.turn
        if turn is None:
            turn = self.begin_turn("-", "(a change made outside a request)")
        try:
            if before is not None and len(before) > MAX_FILE_BYTES:
                raise OSError(f"'{name}' is too big to keep a copy of ({len(before):,} bytes)")
            first = name not in turn.edits or turn.edits[name].reverted
            sha = None
            if first:
                sha = self.keep(before) if before is not None else None
        except OSError as e:
            self.problem(f"{e}; this change to '{name}' can't be undone")
            return False
        plus, minus = line_counts(before, after)
        dirs = [self.ws.display(d) for d in created_dirs]
        entry = {"t": "change", "turn": turn.id, "path": name, "first": first, "before": sha, "after": digest(after),
                 "plus": plus, "minus": minus, "tool": tool}
        if dirs:
            entry["dirs"] = dirs
        self.append(entry)
        edit = turn.edits.get(name)
        if first:
            edit = turn.edits[name] = Edit(name, sha, entry["after"], dirs=dirs)
        else:
            edit.after = entry["after"]
        edit.plus += plus
        edit.minus += minus
        if tool not in edit.tools:
            edit.tools.append(tool)
        return True

    def note_command(self, text: str) -> None:
        """A shell command that may have changed files ran in this request: it can't be undone, and undo says so."""
        turn = self.turn
        if turn is None:
            return
        text = clean_name(text, 200)
        turn.commands.append(text)
        self.append({"t": "command", "turn": turn.id, "text": text})

    # -- looking ------------------------------------------------------------------------------
    def listed(self) -> list[Turn]:
        """The requests `/rewind` offers, oldest first: those still in the conversation, and those whose files are still changed."""
        return [t for t in self.all if not (t.dropped and not t.pending())]

    def pending_turns(self) -> list[Turn]:
        """Turns with changes not yet put back, oldest first."""
        return [t for t in self.all if t.pending()]

    def store_bytes(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self.base / "blobs"):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    pass
        return total

    # -- putting files back -------------------------------------------------------------------
    def current_hash(self, path: str) -> tuple[Path | None, str | None, str]:
        """(real path, hash of the file now or None if absent, problem). A path that leaves the workspace gets no real path."""
        try:
            p = self.ws.path(path)
        except (PermissionError, ValueError) as e:
            return None, None, str(e)
        if p.is_dir():
            return p, None, FOLDER
        try:
            return p, (digest(p.read_bytes()) if p.exists() else None), ""
        except OSError as e:
            return p, None, f"can't be read ({e})"

    def plan(self, turns: list[Turn]) -> Plan:
        """What putting back the changes of these turns (oldest first) would do to each file, without doing it.

        Per file: the content before the *first* of those changes is the target, and the file must still hold what the *last* one wrote."""
        order: dict[str, list[tuple[Turn, Edit]]] = {}
        for t in turns:
            for e in t.pending():
                order.setdefault(e.path, []).append((t, e))
        steps = []
        for path, chain in order.items():
            first, last = chain[0][1], chain[-1][1]
            p, now_hash, problem = self.current_hash(path)
            plus, minus = sum(e.plus for _, e in chain), sum(e.minus for _, e in chain)
            dirs = first.dirs
            if p is None or (problem and problem != FOLDER):
                steps.append(Step(path, "refused", first.before, problem, first, dirs, plus, minus))
            elif problem:
                steps.append(Step(path, "conflict", first.before, problem, first, dirs, plus, minus))
            elif now_hash == first.before:
                steps.append(Step(path, "same", first.before, "", first, dirs, plus, minus))
            elif now_hash == last.after:
                steps.append(Step(path, "delete" if first.before is None else "restore", first.before, "", first, dirs, plus, minus))
            else:
                why = "was deleted since the agent wrote it" if now_hash is None else "has changed since the agent wrote it"
                steps.append(Step(path, "conflict", first.before, why, first, dirs, plus, minus))
        return Plan(list(turns), steps)

    def apply(self, plan: Plan, force: bool = False) -> Outcome:
        """Do it. Conflicts are skipped unless `force`, which first keeps the version that is there now."""
        out = Outcome(commands=plan.commands)
        done: set[str] = set()
        made: list[str] = []
        for step in plan.steps:
            try:
                if step.action == "refused":
                    out.skipped.append((step.path, step.detail))
                    continue
                if step.action == "conflict" and not force:
                    out.skipped.append((step.path, step.detail))
                    continue
                p = self.ws.path(step.path)
                if step.action == "same":
                    out.same.append(step.path)
                    done.add(step.path)
                    continue
                if step.action == "conflict":
                    if p.is_dir():
                        out.skipped.append((step.path, FOLDER))
                        continue
                    if p.exists():
                        out.kept[step.path] = self.keep(p.read_bytes())
                if step.target is None:
                    if p.exists():
                        p.unlink()
                    made.extend(step.dirs)               # tidied after every file is gone: a folder two requests wrote into empties only at the end
                    out.deleted.append(step.path)
                else:
                    src = self.blob(step.target)
                    if not src.exists():
                        out.errors.append((step.path, "the saved copy is gone"))
                        continue
                    data = src.read_bytes()
                    if digest(data) != step.target:
                        out.errors.append((step.path, "the saved copy is damaged"))
                        continue
                    self.write_atomic(p, data)
                    out.restored.append(step.path)
                done.add(step.path)
            except (OSError, PermissionError, ValueError) as e:
                out.errors.append((step.path, str(e)))
        self.remove_empty(list(dict.fromkeys(made)))
        if done:
            self.ws.forget_reads()
            for t in plan.turns:
                paths = [e.path for e in t.pending() if e.path in done]
                if paths:
                    for e in t.pending():
                        if e.path in done:
                            e.reverted = True
                    self.append({"t": "reverted", "turn": t.id, "paths": paths})
        return out

    def drop(self, turns: list[Turn]) -> None:
        """The conversation went back to before these requests."""
        ids = [t.id for t in turns if not t.dropped]
        for t in turns:
            t.dropped = True
        if ids:
            self.append({"t": "dropped", "turns": ids})
        self.turn = None

    @staticmethod
    def write_atomic(p: Path, data: bytes) -> None:
        """Write to a temporary file in the same folder, then rename it over the target: a reader sees the old or the new file, never half."""
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".harness-undo-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def remove_empty(self, dirs: list[str]) -> None:
        """Remove folders a change created, once undoing it leaves them empty (deepest first). Never one that has anything in it."""
        for d in sorted(dirs, key=len, reverse=True):
            try:
                self.ws.path(d).rmdir()
            except (OSError, PermissionError, ValueError):
                pass

    # -- tidying ------------------------------------------------------------------------------
    def sweep(self, chat_ids: set[str]) -> int:
        """Remove the logs of chats that no longer exist, and the copies nothing refers to. Returns how many copies went."""
        if not self.base.is_dir():
            return 0
        used: set[str] = set()
        for log in self.base.glob("*.jsonl"):
            if log.stem not in chat_ids:
                try:
                    log.unlink()
                except OSError:
                    pass
                continue
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                for key in ('"before":"', '"after":"'):
                    i = line.find(key)
                    while i >= 0:
                        used.add(line[i + len(key):i + len(key) + 64])
                        i = line.find(key, i + 1)
        removed, cutoff = 0, time.time() - BLOB_GRACE
        for blob in (self.base / "blobs").glob("*/*"):
            try:
                if blob.name not in used and blob.stat().st_mtime < cutoff:
                    blob.unlink()
                    removed += 1
            except OSError:
                pass
        return removed


# --- for people ------------------------------------------------------------------------------------

def edit_text(e: Edit) -> str:
    what = "new" if e.new else f"+{e.plus} -{e.minus}"
    return f"{clean_name(e.path)} ({what})"


def listing(history: FileHistory) -> str:
    """The `/rewind` list: each request, and what it changed."""
    rows = []
    for n, t in enumerate(history.listed(), 1):
        edits = list(t.edits.values())
        live = [e for e in edits if not e.reverted]
        if not edits:
            changes = "no file changes"
        else:
            shown = ", ".join(edit_text(e) for e in live[:3]) + (f" and {len(live) - 3} more" if len(live) > 3 else "")
            changes = shown if live else "all put back"
        extra = f"; ran {len(t.commands)} command{'s' if len(t.commands) != 1 else ''} that may have changed files" if t.commands else ""
        gone = " [conversation rewound]" if t.dropped else ""
        rows.append(f"{n:>3}  {t.prompt or '(no text)'}{gone}\n       {changes}{extra}")
    return "\n".join(rows)


def plan_text(plan: Plan) -> str:
    lines = []
    for s in plan.steps:
        counts = (f" (new, {s.plus} line{'' if s.plus == 1 else 's'})" if s.edit is not None and s.edit.new
                  else f" (+{s.plus} -{s.minus} in the change)")
        verb = {"restore": "put back", "delete": "remove", "same": "already as it was", "conflict": "SKIPPED", "refused": "SKIPPED"}[s.action]
        why = f": {s.detail}" if s.detail else ""
        lines.append(f"  {verb:<18} {clean_name(s.path)}{counts if s.action in ('restore', 'delete') else ''}{why}")
    return "\n".join(lines)


def outcome_text(out: Outcome, force_hint: bool = True) -> str:
    lines = []
    if out.restored:
        lines.append("put back: " + ", ".join(clean_name(p) for p in out.restored))
    if out.deleted:
        lines.append("removed (the agent created them): " + ", ".join(clean_name(p) for p in out.deleted))
    if out.same:
        lines.append("already as they were: " + ", ".join(clean_name(p) for p in out.same))
    for path, why in out.skipped:
        lines.append(f"SKIPPED {clean_name(path)}: {why}")
    for path, why in out.errors:
        lines.append(f"FAILED {clean_name(path)}: {why}")
    for path, sha in out.kept.items():
        lines.append(f"your version of {clean_name(path)} was kept (copy {sha[:12]}) before it was replaced")
    if out.commands:
        lines.append(f"not undone: {len(out.commands)} shell command(s) ran in these requests and may have changed files "
                     f"({'; '.join(clean_name(c, 60) for c in out.commands[:3])}). The harness can't know which.")
    if force_hint and out.skipped and any("changed" in why or "deleted" in why for _p, why in out.skipped):
        lines.append("files you changed since were left alone; add `force` to put the agent's earlier version back over them")
    return "\n".join(lines) or "nothing to put back"
