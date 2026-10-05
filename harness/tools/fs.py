"""Lesson 07: the first real tools, for looking at files in the workspace.

WARNING: not sandboxed yet. A path like "../../secret.txt" escapes the workspace.
That's deliberate: Lesson 17 attacks it, Lesson 18 fixes it.
"""
from pathlib import Path

from harness.tools.base import Tool

PATH_PARAM = {"type": "string", "description": "Path relative to the workspace root, e.g. notes.txt or recipes/"}


def workspace_snapshot(workspace: Path, depth: int = 2, limit: int = 50) -> str:
    """An indented file tree for the system prompt, so the model knows what exists up front."""
    lines = []

    def walk(folder: Path, indent: str, level: int):
        for p in sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if len(lines) >= limit:
                return
            lines.append(f"{indent}{p.name}/" if p.is_dir() else f"{indent}{p.name}")
            if p.is_dir() and level < depth:
                walk(p, indent + "  ", level + 1)

    walk(workspace, "", 1)
    if len(lines) >= limit:
        lines.append("... (more files not shown; use list_dir)")
    return "\n".join(lines) or "(empty)"


def make_fs_tools(workspace: Path) -> list[Tool]:
    """Build file tools bound to one workspace folder."""

    def list_dir(path: str = ".") -> str:
        target = workspace / path
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))  # folders first
        lines = [f"{p.name}/" if p.is_dir() else f"{p.name}  ({p.stat().st_size} bytes)" for p in entries]
        return "\n".join(lines) or "(empty folder)"

    def read_file(path: str) -> str:
        return (workspace / path).read_text(encoding="utf-8")

    return [
        Tool(
            name="list_dir",
            description="List the files and folders inside a workspace folder. Folders end with '/'.",
            parameters={"type": "object", "properties": {"path": PATH_PARAM}},
            fn=list_dir,
        ),
        Tool(
            name="read_file",
            description="Read a text file from the workspace and return its full contents.",
            parameters={"type": "object", "properties": {"path": PATH_PARAM}, "required": ["path"]},
            fn=read_file,
        ),
    ]
