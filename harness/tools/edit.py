"""Lesson 12: changing files safely.

`edit_file` replaces an exact piece of text; `write_file` creates or overwrites a whole file.
Both refuse to touch a file the model hasn't read, or one that changed since it was read,
and both return a diff so the model (and the user, when approving) can see what changes.
"""
import difflib
import hashlib
import re

from harness.tools.base import Tool, tool
from harness.tools.fs import read_lines
from harness.workspace import FileStamp, Workspace

MAX_EDIT_BYTES = 1_000_000
DIFF_CONTEXT = 2
MAX_DIFF_LINES = 60
# "    12\t" — the prefix read_file adds. Models sometimes copy it into old_string.
LINE_PREFIX = re.compile(r"^ *\d+\t", re.MULTILINE)


class EditError(Exception):
    """A planned edit can't be applied. The message is written for the model."""


def lines_word(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unified_diff(name: str, before: str, after: str) -> str:
    lines = list(difflib.unified_diff(before.splitlines(), after.splitlines(), f"a/{name}", f"b/{name}",
                                      n=DIFF_CONTEXT, lineterm=""))
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"... ({len(lines) - MAX_DIFF_LINES} more diff lines)"]
    return "\n".join(lines)


def make_edit_tools(ws: Workspace, history=None) -> list[Tool]:
    """`history` (Lesson 43), when given, is shown each file's exact bytes just before a tool overwrites them, so the change can be undone."""

    def check_fresh(p, name: str) -> bytes:
        """The file must have been read in this conversation and not changed since.

        When it hasn't been (or has changed), the error includes the current content, which
        counts as reading it, and says plainly that nothing was changed. Measured (Lesson 24):
        after a bare "read it first" refusal the model read the file and then believed its edit
        had been applied, never retrying it.
        """
        stamp: FileStamp | None = ws.reads.get(p)
        if stamp is None:
            raise EditError(f"the edit was NOT made: you hadn't read '{name}' yet. Its current content is "
                            f"below (this counts as reading it). If your old_string matches it, call the "
                            f"tool again with the same arguments.\n{current(name)}")
        data = p.read_bytes()
        if p.stat().st_mtime_ns != stamp.mtime_ns and digest(data) != stamp.digest:
            ws.forget_reads()
            raise EditError(f"the edit was NOT made: '{name}' changed since you read it (by the user or "
                            f"another program). Its current content is below; call the tool again with an "
                            f"old_string that matches it.\n{current(name)}")
        if len(data) > MAX_EDIT_BYTES:
            raise EditError(f"'{name}' is too large to edit ({len(data):,} bytes; the limit is {MAX_EDIT_BYTES:,})")
        return data

    def current(name: str) -> str:
        """The file as read_file would show it, recorded as read."""
        try:
            return read_lines(ws, name)
        except (OSError, ValueError) as e:
            return f"(could not show it: {e})"

    def remember(p, data: bytes) -> None:
        """After our own write the model knows the new content: keep the file 'fresh'."""
        st = p.stat()
        ws.reads[p] = FileStamp(st.st_mtime_ns, st.st_size, digest=digest(data))

    def plan_edit(path: str, old_string: str, new_string: str, replace_all: bool):
        """Work out the edit without writing anything. Returns (p, name, before, after, count)."""
        p = ws.path(path)
        name = ws.display(p)
        if old_string == new_string:
            raise EditError("old_string and new_string are identical, so there is nothing to change")
        if not p.exists():
            raise EditError(f"no file named '{name}'.{ws.suggest(p)} To create a new file, use write_file")
        if p.is_dir():
            raise EditError(f"'{name}' is a folder")
        if old_string == "":
            raise EditError("old_string is empty. Copy the exact text to replace from read_file, "
                            "or use write_file to replace the whole file")
        data = check_fresh(p, name)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise EditError(f"'{name}' is not UTF-8 text, so it can't be edited safely") from None

        old, new = old_string, new_string
        if "\r\n" in text and "\r\n" not in old:      # file uses Windows line endings, model sent \n
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        count = text.count(old)
        if count == 0 and LINE_PREFIX.search(old):    # model copied read_file's line numbers
            stripped_old = LINE_PREFIX.sub("", old)
            if text.count(stripped_old):
                old, new, count = stripped_old, LINE_PREFIX.sub("", new), text.count(stripped_old)
        if count == 0:
            raise EditError(f"old_string was not found in '{name}'. It must match the file exactly, "
                            "including spaces and indentation, without read_file's line numbers."
                            + closest_hint(text, old))
        if count > 1 and not replace_all:
            lines = [text.count("\n", 0, m.start()) + 1 for m in re.finditer(re.escape(old), text)]
            raise EditError(f"old_string appears {count} times in '{name}' (lines {', '.join(map(str, lines[:10]))}). "
                            "Include more surrounding lines so it matches exactly one place, "
                            "or set replace_all=true to change every occurrence")
        after = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        return p, name, text, after, count if replace_all else 1

    def check_edit(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str | None:
        try:
            plan_edit(path, old_string, new_string, replace_all)
        except EditError as e:
            return f"Error: {e}"
        return None

    def preview_edit(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        _, name, before, after, _ = plan_edit(path, old_string, new_string, replace_all)
        return unified_diff(name, before, after)

    @tool(read_only=False, concurrency_safe=False)
    def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        """Replace exact text in a file. Read the file with read_file first.

        old_string must match the file exactly (spaces and indentation included) and be unique
        in the file: include enough surrounding lines to pick one place. Do not include the
        line numbers that read_file shows; they are not part of the file. To change every
        occurrence, set replace_all=true. To create a file, use write_file.

        Args:
            path: File to edit, relative to the workspace root.
            old_string: The exact text to replace.
            new_string: The text to put in its place.
            replace_all: Replace every occurrence instead of exactly one.
        """
        p, name, before, after, count = plan_edit(path, old_string, new_string, replace_all)
        data = after.encode("utf-8")
        if history is not None:
            history.record(p, p.read_bytes(), data, "edit_file")     # the copy is kept before the write, not after
        p.write_bytes(data)          # bytes: keep the file's own line endings exactly
        remember(p, data)
        noun = "replacement" if count == 1 else "replacements"
        return f"Edited {name}: {count} {noun}.\n{unified_diff(name, before, after)}"

    edit_file.check = check_edit
    edit_file.preview = preview_edit

    def check_write(path: str, content: str) -> str | None:
        p = ws.path(path)
        if p.is_dir():
            return f"Error: '{ws.display(p)}' is a folder"
        if p.exists():
            try:
                check_fresh(p, ws.display(p))
            except EditError as e:
                return f"Error: {e}. (write_file replaces the whole file; for small changes use edit_file)"
        return None

    def preview_write(path: str, content: str) -> str:
        p = ws.path(path)
        name = ws.display(p)
        if not p.exists():
            lines = content.splitlines()
            shown = "\n".join(f"+{line}" for line in lines[:MAX_DIFF_LINES])
            more = f"\n... ({len(lines) - MAX_DIFF_LINES} more lines)" if len(lines) > MAX_DIFF_LINES else ""
            return f"new file {name} ({lines_word(len(lines))})\n{shown}{more}"
        return unified_diff(name, p.read_text(encoding="utf-8", errors="replace"), content)

    @tool(read_only=False, concurrency_safe=False,
          destructive=lambda args: ws.path(args["path"]).exists())
    def write_file(path: str, content: str) -> str:
        """Create a file, or replace a whole file's contents. Missing folders are created.

        To overwrite an existing file you must have read it first. For small changes to an
        existing file prefer edit_file, which changes only the part you name.

        Args:
            path: File to write, relative to the workspace root.
            content: The complete new contents of the file.
        """
        error = check_write(path, content)
        if error:
            raise EditError(error.removeprefix("Error: "))
        p = ws.path(path)
        name = ws.display(p)
        existed = p.exists()
        before = p.read_text(encoding="utf-8", errors="replace") if existed else ""
        data = content.encode("utf-8")
        if history is not None:
            made = []                                 # folders this write creates, so undoing it can remove them again
            for d in (p.parent, *p.parent.parents):
                if d.exists():
                    break
                made.append(d)
            history.record(p, p.read_bytes() if existed else None, data, "write_file", made)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        remember(p, data)
        n = len(content.splitlines())
        if not existed:
            return f"Created {name} ({lines_word(n)})."
        return (f"Overwrote {name} ({lines_word(n)}, was {len(before.splitlines())}).\n"
                f"{unified_diff(name, before, content)}")

    write_file.check = check_write
    write_file.preview = preview_write
    return [edit_file, write_file]


def closest_hint(text: str, old: str) -> str:
    """Show the line most similar to old_string's first line, to help the model retry."""
    first = next((line for line in old.splitlines() if line.strip()), "")
    if not first:
        return ""
    lines = text.splitlines()
    best = difflib.get_close_matches(first, lines, n=1, cutoff=0.6)
    if not best:
        return ""
    n = lines.index(best[0]) + 1
    return f"\nThe most similar line in the file is line {n}: {best[0]!r}"
