"""Lesson 23: @mentions. `fix the bug in @project/shop/cart.py` attaches that file to the message.

The file is read with read_file's own reader, so it is recorded as read: the model can edit it
right away without spending a step on reading it. Folders attach their listing. A mention that
isn't a file or folder in the workspace (an e-mail address, a decorator) is left alone.
"""
import re

from harness.tools.fs import read_lines
from harness.workspace import OutsideWorkspace, Workspace

MENTION = re.compile(r"(?<![\w@])@([\w.\-/\\]+[\w/\\])")   # @path, not foo@bar.com
MAX_MENTIONS = 5


def expand_mentions(text: str, ws: Workspace) -> tuple[str, list[str]]:
    """Return (message for the model, list of attached paths)."""
    attached, blocks = [], []
    for match in MENTION.finditer(text):
        rel = match.group(1).replace("\\", "/")
        try:
            p = ws.path(rel)
        except OutsideWorkspace:                     # not ours to attach (Lesson 28)
            continue
        if rel in attached or not p.exists() or len(attached) >= MAX_MENTIONS:
            continue
        if p.is_dir():
            listing = "\n".join(sorted(f"{c.name}/" if c.is_dir() else c.name for c in p.iterdir()))
            blocks.append(f'<folder path="{ws.display(p)}">\n{listing}\n</folder>')
        else:
            try:
                blocks.append(f'<file path="{ws.display(p)}">\n{read_lines(ws, rel)}\n</file>')
            except (ValueError, OSError) as e:          # binary, unreadable: say so instead
                blocks.append(f'<file path="{ws.display(p)}">\n(not attached: {e})\n</file>')
        attached.append(rel)
    if not blocks:
        return text, []
    return text + "\n\nThe user attached these with @ (already read; no need to read them again):\n" + \
        "\n".join(blocks), attached
