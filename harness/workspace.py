"""Lessons 10 and 28: the workspace, the one place where tool paths are turned into real files.

Every file tool goes through `Workspace.path()`, so path rules live in a single function. Since
Lesson 28 it is a jail: a path is resolved first (`..`, absolute paths, drive letters, symlinks
and Windows junctions all collapse into one real location) and refused unless that location is
inside the workspace or a folder the user added. Names Windows treats specially are refused
before resolving, because they don't mean what they look like (see `check_name`).

The workspace also remembers which files the model has read (and their modification time).
Lesson 12's edit tools use that to refuse blind or stale edits.
"""
import difflib
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# Folders that are never interesting to a model and often huge.
IGNORED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules",
                ".mypy_cache", ".pytest_cache", ".ruff_cache", ".harness", ".idea", ".vscode"}

# Windows device names: "NUL", "con.txt" or "COM1.log" open a device, not a file.
RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$", re.IGNORECASE)


class OutsideWorkspace(PermissionError):
    """A tool path that would leave the workspace. The message is written for the model."""


def check_name(relative: str) -> None:
    """Refuse path parts that Windows reinterprets. Applied on every OS, so behaviour is the
    same everywhere (and a repository using such names breaks on Windows anyway)."""
    parts = [p for p in re.split(r"[\\/]", relative) if p not in ("", ".", "..")]
    for i, part in enumerate(parts):
        if ":" in part and not (i == 0 and re.fullmatch(r"[A-Za-z]:", part)):
            raise OutsideWorkspace(f"'{relative}': ':' isn't allowed in file names "
                                   "(on Windows it opens a hidden data stream)")
        if part.endswith((".", " ")):
            raise OutsideWorkspace(f"'{relative}': names can't end with a dot or a space "
                                   "(Windows silently removes them, so the name means another file)")
        if RESERVED.match(part.strip()):
            raise OutsideWorkspace(f"'{relative}': '{part}' is a Windows device name, not a file")


@dataclass
class FileStamp:
    """What a file looked like when the model last read it."""
    mtime_ns: int
    size: int
    ranges: set = field(default_factory=set)   # (offset, limit) pairs already returned
    digest: str | None = None                  # sha256 of the content, to spot false "changed" alarms


class Workspace:
    def __init__(self, root: Path | str, extra_dirs: list[Path | str] = ()):
        self.root = Path(root).resolve()
        # Folders outside the root the user allowed (the additional_directories setting).
        self.extra_dirs = [Path(d).resolve() for d in extra_dirs]
        self.reads: dict[Path, FileStamp] = {}

    def path(self, relative: str) -> Path:
        """Model-supplied path → the real absolute path, which is inside the workspace.

        Raises OutsideWorkspace otherwise. `resolve()` does the hard part: it applies `..`,
        follows symlinks and junctions, and makes the result absolute, so the check below
        compares where the path really leads, not how it is spelled.
        """
        check_name(relative)
        p = (self.root / relative).resolve()
        if not self.contains(p):
            raise OutsideWorkspace(f"'{relative}' is outside the workspace. Tools can only use files "
                                   "inside it; paths are relative to the workspace root.")
        return p

    def contains(self, p: Path) -> bool:
        """True if the (resolved) path is the root, an added folder, or inside one of them.
        Path comparison ignores case on Windows, like the file system does."""
        return any(p == d or p.is_relative_to(d) for d in (self.root, *self.extra_dirs))

    def leads_outside(self, p: Path) -> bool:
        """For folder walks: does this entry (a link, typically) lead out of the workspace?"""
        try:
            return not self.contains(p.resolve())
        except OSError:
            return True

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
