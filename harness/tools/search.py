"""Lesson 11: finding things. `glob` finds files by name, `grep` finds text inside files.

Both are pure Python (pathlib, os.walk, re), skip folders like .git and node_modules, skip
binary files, and cap their output with a note saying how to narrow the search.
"""
import fnmatch
import os
import re
from pathlib import Path
from typing import Literal

from harness.tools.base import Tool, tool
from harness.workspace import IGNORED_DIRS, Workspace

GLOB_LIMIT = 100
GREP_MAX_FILE_BYTES = 2_000_000   # bigger files are skipped (logs, dumps, bundles)
MAX_LINE_CHARS = 300


def walk_files(root: Path):
    """Every file under root, skipping ignored folders, in a stable order."""
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for name in sorted(files):
            yield Path(folder) / name


def _is_binary(p: Path) -> bool:
    with open(p, "rb") as f:
        return b"\0" in f.read(8192)


def _matches_glob(rel: str, pattern: str) -> bool:
    """'*.py' matches by file name anywhere; 'src/**/*.py' matches the relative path."""
    if "/" not in pattern:
        return fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pattern)
    # fnmatch's * already crosses folders; also let "**/" match zero folders
    variants = {pattern, pattern.replace("/**/", "/")}
    if pattern.startswith("**/"):
        variants.add(pattern[3:])
    return any(fnmatch.fnmatch(rel, v) for v in variants)


def make_search_tools(ws: Workspace) -> list[Tool]:

    @tool(read_only=True, concurrency_safe=True)
    def glob(pattern: str, path: str = ".") -> str:
        """Find files by name pattern. Returns paths, most recently modified first.

        Examples: "*.py" (Python files in any folder), "src/**/test_*.py", "**/README.md".
        Use grep instead to search inside files.

        Args:
            pattern: A glob pattern. Without a "/" it matches file names in every folder.
            path: Folder to search in, relative to the workspace root.
        """
        base = ws.path(path)
        if not base.is_dir():
            raise NotADirectoryError(f"no folder named '{ws.display(base)}'.{ws.suggest(base)}")
        found = [p for p in walk_files(base) if _matches_glob(p.relative_to(base).as_posix(), pattern)]
        prefix = ws.display(base) + "/"
        if not found and base != ws.root and pattern.startswith(prefix):
            # The model repeated the folder in the pattern: glob("project/a.py", path="project")
            pattern = pattern[len(prefix):]
            found = [p for p in walk_files(base) if _matches_glob(p.relative_to(base).as_posix(), pattern)]
        if not found:
            return f"No files match '{pattern}' in {ws.display(base)}/."
        found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        lines = [ws.display(p) for p in found[:GLOB_LIMIT]]
        if len(found) > GLOB_LIMIT:
            lines.append(f"... and {len(found) - GLOB_LIMIT} more. Use a more specific pattern or path.")
        return "\n".join(lines)

    @tool(read_only=True, concurrency_safe=True)
    def grep(pattern: str, path: str = ".", glob: str | None = None, ignore_case: bool = False,
             output: Literal["lines", "files", "count"] = "lines", context: int = 0,
             limit: int = 50) -> str:
        """Search inside files for a regular expression (Python `re` syntax).

        Returns matching lines as `path:line: text`. To search for plain text containing
        characters like ( [ . * + ?, escape them with a backslash; if the pattern isn't a
        valid regular expression it is searched as plain text.

        Args:
            pattern: The regular expression, e.g. "def total" or "TODO|FIXME".
            path: File or folder to search, relative to the workspace root.
            glob: Only search files matching this name pattern, e.g. "*.py".
            ignore_case: Match upper and lower case alike.
            output: "lines" = matching lines, "files" = just the file names, "count" = matches per file.
            context: Lines to show before and after each match (only for output="lines").
            limit: Maximum lines (or files) in the result.
        """
        flags = re.IGNORECASE if ignore_case else 0
        note = ""
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            rx = re.compile(re.escape(pattern), flags)
            note = f"(not a valid regular expression: {e}; searched for it as plain text)\n"

        base = ws.path(path)
        if not base.exists():
            raise FileNotFoundError(f"no file or folder named '{ws.display(base)}'.{ws.suggest(base)}")
        candidates = [base] if base.is_file() else walk_files(base)

        out: list[str] = []
        files_matched = total_matches = 0
        more = False
        for p in candidates:
            rel = ws.display(p)
            if glob and not _matches_glob(rel, glob):
                continue
            try:
                if p.stat().st_size > GREP_MAX_FILE_BYTES or _is_binary(p):
                    continue
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            hits = [i for i, line in enumerate(lines) if rx.search(line)]
            if not hits:
                continue
            files_matched += 1
            total_matches += len(hits)
            if len(out) >= limit:
                more = True
                continue
            if output == "files":
                out.append(rel)
            elif output == "count":
                out.append(f"{rel}: {len(hits)}")
            else:
                hit_set, last = set(hits), None   # last = index of the last line printed
                for i in hits:
                    start, end = max(0, i - context), min(len(lines), i + context + 1)
                    if last is not None and start > last + 1:
                        out.append("--")             # a gap between context groups, like grep
                    for j in range(max(start, (last or -1) + 1), end):
                        sep = ":" if j in hit_set else "-"
                        text = lines[j] if len(lines[j]) <= MAX_LINE_CHARS else lines[j][:MAX_LINE_CHARS] + "…"
                        out.append(f"{rel}{sep}{j + 1}{sep} {text}")
                        last = j
                    if len(out) >= limit:
                        more = True
                        break

        if not out:
            where = ws.display(base) + ("" if base.is_file() else "/")
            return note + f"No matches for '{pattern}' in {where}" + (f" (files: {glob})" if glob else "") + "."
        summary = (f"{total_matches} match{'es' if total_matches != 1 else ''} in "
                   f"{files_matched} file{'s' if files_matched != 1 else ''}")
        if more:
            summary += f"; showing the first {limit} lines. Narrow the pattern, path or glob to see the rest"
        return note + "\n".join(out[:limit]) + f"\n({summary})"

    return [glob, grep]
