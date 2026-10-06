"""Lesson 34: an audit log: what the agent did, decided and was allowed to do, in a file you can trust.

One JSON object per line, appended and never rewritten:

    {"t": "2026-10-06T20:11:03", "session": "a1b2c3", "kind": "decision", "tool": "run_shell",
     "subject": "git push", "action": "ask", "reason": "...", "prev": "<hash of the previous line>"}

Three properties matter:

* **Written by the harness, not the model.** It lives in the user's settings folder, outside every
  project, so a tool call can't edit it (and a repository can't ship one).
* **Free of secrets.** Every value is redacted (harness/security/redact.py) and shortened before it
  is written, so the log can be read, shared or kept without becoming a second place secrets leak.
* **Tamper-evident.** Each line carries the hash of the line before it. Change, delete or reorder a
  line and `verify()` finds the first place where the chain breaks. (It shows tampering. It can't
  prevent it: someone with write access to the file can rewrite the whole chain. For that you
  need a copy somewhere they can't reach.)
"""
import datetime
import hashlib
import json
import os
import threading
from pathlib import Path

from harness.security.redact import redact

MAX_FIELD = 500                 # characters kept of any one value
MAX_FILE = 10_000_000           # bytes before the log is rotated
GENESIS = "0" * 16


def digest(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]


def shorten(value, limit: int = MAX_FIELD):
    """Redacted, one-line-safe and short. Non-text values (numbers, booleans, lists of them) pass through."""
    if isinstance(value, str):
        text = redact(value).text
        return text if len(text) <= limit else text[:limit - 1] + "…"
    if isinstance(value, dict):
        return {str(k): shorten(v, limit) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [shorten(v, limit) for v in list(value)[:30]]
    return value


class AuditLog:
    def __init__(self, path: Path, session: str):
        self.path, self.session = Path(path), session
        self.lock = threading.Lock()
        self.last = self._last_hash()
        self.failed = False            # set when the log can't be written; the app says so once

    def _last_hash(self) -> str:
        try:
            with open(self.path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 65536))
                lines = f.read().decode("utf-8", errors="replace").splitlines()
            return digest(lines[-1]) if lines else GENESIS
        except OSError:
            return GENESIS

    def write(self, kind: str, **fields) -> None:
        """Append one entry. Never raises: a log that can't be written must not stop the agent (but
        `failed` records it)."""
        entry = {"t": datetime.datetime.now().isoformat(timespec="seconds"), "session": self.session, "kind": kind,
                 **{k: shorten(v) for k, v in fields.items() if v is not None}}
        with self.lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > MAX_FILE:
                    self.path.replace(self.path.with_suffix(".jsonl.1"))
                entry["prev"] = self.last
                line = json.dumps(entry, ensure_ascii=False)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
                if os.name != "nt":
                    os.chmod(self.path, 0o600)
                self.last = digest(line)
            except OSError:
                self.failed = True

    def tail(self, n: int = 20) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"kind": "unreadable line", "text": line[:80]})
        return out


def verify(path: Path) -> tuple[bool, int, str | None]:
    """(chain intact, entries checked, what is wrong). The first entry of a file is trusted as the start
    (a rotated file continues a chain that lives in the older one)."""
    previous, count = None, 0
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        return False, 0, f"can't read the log: {e}"
    for number, line in enumerate(lines, 1):
        try:
            entry = json.loads(line)
        except ValueError:
            return False, count, f"line {number} isn't valid JSON"
        if previous is not None and entry.get("prev") != previous:
            return False, count, f"line {number} doesn't follow line {number - 1}: a line was changed, removed or reordered"
        previous, count = digest(line), count + 1
    return True, count, None


def format_entry(entry: dict) -> str:
    """One readable line for /audit."""
    rest = {k: v for k, v in entry.items() if k not in ("t", "session", "kind", "prev")}
    details = " ".join(f"{k}={v!r}" if not isinstance(v, (int, float)) else f"{k}={v}" for k, v in rest.items())
    return f"{entry.get('t', '?')[11:]} {entry.get('kind', '?'):<12} {details}"
