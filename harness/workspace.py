"""Lesson 10: the workspace, the one place where tool paths are turned into real files.

Every file tool goes through `Workspace.path()`, so path rules live in a single function.
Today it only joins paths; Lesson 28 turns it into a jail that refuses to leave the root.

The workspace also remembers which files the model has read (and their modification time).
Lesson 12's edit tools use that to refuse blind or stale edits.
"""
import difflib
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

# Folders that are never interesting to a model and often huge.
IGNORED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules",
                ".mypy_cache", ".pytest_cache", ".ruff_cache", ".harness", ".idea", ".vscode"}


@dataclass
class FileStamp:
    """What a file looked like when the model last read it."""
    mtime_ns: int
    size: int
    ranges: set = field(default_factory=set)   # (offset, limit) pairs already returned
    digest: str | None = None                  # sha256 of the content, to spot false "changed" alarms


class Workspace:
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.reads: dict[Path, FileStamp] = {}

    def path(self, relative: str) -> Path:
        """Model-supplied path → absolute path. NOT confined to the root yet (Lesson 28)."""
        return (self.root / relative).resolve()

    def display(self, p: Path) -> str:
        """How we show a path to the model: relative, with forward slashes."""
        try:
            return p.relative_to(self.root).as_posix() or "."
        except ValueError:
            return str(p)

    # --- read tracking (used by read_file, checked by edit tools) ---

    def record_read(self, p: Path, offset: int | None = None, limit: int | None = None,
                    data: bytes | None = None) -> None:
        st = p.stat()
        stamp = self.reads.get(p)
        if stamp is None or stamp.mtime_ns != st.st_mtime_ns:
            digest = hashlib.sha256(data).hexdigest() if data is not None else None
            stamp = self.reads[p] = FileStamp(st.st_mtime_ns, st.st_size, digest=digest)
        stamp.ranges.add((offset, limit))

    def unchanged_since_read(self, p: Path, offset=None, limit=None) -> bool:
        """True if exactly this range was already returned and the file hasn't changed."""
        stamp = self.reads.get(p)
        return (stamp is not None and (offset, limit) in stamp.ranges
                and p.exists() and p.stat().st_mtime_ns == stamp.mtime_ns)

    def forget_reads(self) -> None:
        """Called when old tool results leave the context (Module 6): re-reads must return content."""
        for stamp in self.reads.values():
            stamp.ranges.clear()

    # --- helpers for friendly errors ---

    def suggest(self, p: Path) -> str:
        """' Did you mean: a, b?' for a missing path, based on its siblings."""
        parent = p.parent
        if not parent.is_dir():
            return ""
        names = os.listdir(parent)
        close = difflib.get_close_matches(p.name, names, n=3, cutoff=0.7)
        if not close:
            return ""
        return " Did you mean: " + ", ".join(self.display(parent / c) for c in close) + "?"
