"""Lesson 31: which folders the user trusts.

Opening a repository you cloned is not the same as opening your own project: its files, including
the ones the agent will read, were written by its author. `/trust` records that you vouch for a
folder. The list lives in the *user's* config folder, never in the project, so a repository can't
declare itself trusted. In a folder that isn't trusted, file text and command output count as
untrusted content (harness/security/taint.py).
"""
import json
import os
from pathlib import Path

FILE = "trusted-folders.json"


def key(folder: Path) -> str:
    resolved = str(Path(folder).resolve())
    return resolved.casefold() if os.name == "nt" else resolved


def _load(user_dir: Path) -> list[str]:
    try:
        folders = json.loads((user_dir / FILE).read_text(encoding="utf-8")).get("folders", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [k for k in folders if isinstance(k, str)] if isinstance(folders, list) else []


def is_trusted(folder: Path, user_dir: Path) -> bool:
    """True when this folder, or a folder above it, was trusted."""
    here = key(folder)
    return any(here == t or here.startswith(t.rstrip("\\/") + os.sep) for t in _load(user_dir))


def set_trusted(folder: Path, user_dir: Path, trusted: bool) -> None:
    folders = [t for t in _load(user_dir) if t != key(folder)]
    if trusted:
        folders.append(key(folder))
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / FILE).write_text(json.dumps({"folders": sorted(folders)}, indent=2) + "\n", encoding="utf-8")
