"""Lessons 07-10: tools for looking at files in the workspace.

WARNING: not sandboxed yet. A path like "../../secret.txt" escapes the workspace.
That's deliberate: Lesson 27 attacks it, Lesson 28 fixes it (in Workspace.path).
"""
from pathlib import Path

from harness.tools.base import Tool, tool
from harness.workspace import IGNORED_DIRS, Workspace

READ_LIMIT = 300          # lines per read_file call by default
MAX_LINE_CHARS = 500      # longer lines are cut (minified files, data blobs)
READ_BUDGET_CHARS = 7_000 # stop adding lines past this, just under the registry's 8,000 cap
BINARY_SNIFF = 8_192      # a NUL byte in the first 8 KB means "binary"

UNCHANGED = ("(file unchanged since you read these lines earlier in this conversation; "
             "use that earlier result)")


def as_workspace(ws: Path | Workspace) -> Workspace:
    return ws if isinstance(ws, Workspace) else Workspace(ws)


def workspace_snapshot(workspace: Path | Workspace, depth: int = 2, limit: int = 50) -> str:
    """An indented file tree for the system prompt, so the model knows what exists up front."""
    ws = as_workspace(workspace)
    root = ws.root
    lines = []

    def walk(folder: Path, indent: str, level: int):
        for p in sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if len(lines) >= limit:
                return
            if p.is_dir() and p.name in IGNORED_DIRS:
                continue
            if ws.leads_outside(p):            # a link out of the workspace: name it, don't enter
                lines.append(f"{indent}{p.name}  (link outside the workspace)")
                continue
            lines.append(f"{indent}{p.name}/" if p.is_dir() else f"{indent}{p.name}")
            if p.is_dir() and level < depth:
                walk(p, indent + "  ", level + 1)

    walk(root, "", 1)
    if len(lines) >= limit:
        lines.append("... (more files not shown; use list_dir)")
    return "\n".join(lines) or "(empty)"


def read_lines(ws: Workspace, path: str, offset: int = 1, limit: int = READ_LIMIT) -> str:
    """The body of read_file, shared with other tools that show files."""
    p = ws.path(path)
    name = ws.display(p)
    if not p.exists():
        raise FileNotFoundError(f"no file named '{name}'.{ws.suggest(p)}")
    if p.is_dir():
        raise IsADirectoryError(f"'{name}' is a folder; use list_dir to see what's inside")
    if limit < 1:
        raise ValueError("limit must be at least 1")

    data = p.read_bytes()
    if b"\0" in data[:BINARY_SNIFF]:
        raise ValueError(f"'{name}' is a binary file ({len(data):,} bytes); it can't be shown as text")
    try:
        text, note = data.decode("utf-8"), ""
    except UnicodeDecodeError:
        text, note = data.decode("utf-8", errors="replace"), " (not valid UTF-8; bad bytes shown as �)"
    lines = text.splitlines()
    # Models often count from 0, and "the last lines" is a common question: accept both.
    if offset == 0:
        offset = 1
    elif offset < 0:
        offset = max(1, len(lines) + offset + 1)   # -1 = the last line
    if ws.unchanged_since_read(p, offset, limit):
        return UNCHANGED
    ws.record_read(p, offset, limit, data)
    if not lines:
        return f"({name} is empty)"
    if offset > len(lines):
        return (f"(offset {offset} is past the end: {name} has {len(lines)} lines; "
                f"the last line is offset={len(lines)}, or use offset=-1)")

    out, used, last = [], 0, offset - 1
    for n in range(offset, min(offset + limit, len(lines) + 1)):
        line = lines[n - 1]
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + f"… [line cut: {len(line):,} chars]"
        row = f"{n:>6}\t{line}"
        if out and used + len(row) > READ_BUDGET_CHARS:
            break
        out.append(row)
        used += len(row) + 1
        last = n
    header = f"{name}: lines {offset}-{last} of {len(lines)}{note}"
    if last < len(lines):
        header += f". More below: read_file(path={name!r}, offset={last + 1})"
    return header + "\n" + "\n".join(out)


def make_fs_tools(workspace: Path | Workspace) -> list[Tool]:
    """Build the read-only file tools bound to one workspace."""
    ws = as_workspace(workspace)

    @tool(read_only=True, concurrency_safe=True)
    def list_dir(path: str = ".") -> str:
        """List the files and folders inside a workspace folder. Folders end with '/'.

        Args:
            path: Folder relative to the workspace root, e.g. "." or "recipes/".
        """
        target = ws.path(path)
        if not target.exists():
            raise FileNotFoundError(f"no folder named '{ws.display(target)}'.{ws.suggest(target)}")
        if target.is_file():
            raise NotADirectoryError(f"'{ws.display(target)}' is a file; use read_file to read it")
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))  # folders first
        lines = [f"{p.name}  (link outside the workspace)" if ws.leads_outside(p)
                 else f"{p.name}/" if p.is_dir() else f"{p.name}  ({p.stat().st_size:,} bytes)" for p in entries]
        return "\n".join(lines) or "(empty folder)"

    @tool(read_only=True, concurrency_safe=True)
    def read_file(path: str, offset: int = 1, limit: int = READ_LIMIT) -> str:
        """Read a text file from the workspace. Lines come back numbered, like `cat -n`.

        Long files are returned in parts: the first line of the result says which lines you
        got and how to read the next part. To see a specific place, pass offset (and limit).
        The line numbers are for reference only; they are not part of the file.

        Args:
            path: File path relative to the workspace root, e.g. "notes.txt".
            offset: First line to return. 1 is the first line; negative counts from the end (-1 is the last line).
            limit: Maximum number of lines to return.
        """
        return read_lines(ws, path, offset, limit)

    return [list_dir, read_file]
