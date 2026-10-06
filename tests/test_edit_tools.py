"""Lesson 12: edits are exact, fresh, reviewable and preserve the file's format."""
import os

import pytest

from harness.agent import Agent
from harness.tools.edit import EditError, make_edit_tools
from harness.tools.fs import make_fs_tools
from harness.workspace import Workspace
from tests.fakes import ScriptedProvider, call, calls, final

CART = "class Cart:\n    def subtotal(self):\n        return sum(price for _, price, qty in self.items)\n"


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "cart.py").write_text(CART, encoding="utf-8")
    (tmp_path / "dup.txt").write_text("x = 1\ny = 2\nx = 1\n", encoding="utf-8")
    (tmp_path / "win.txt").write_bytes(b"one\r\ntwo\r\nthree\r\n")
    return Workspace(tmp_path)


@pytest.fixture
def t(ws):
    return {tool.name: tool for tool in make_fs_tools(ws) + make_edit_tools(ws)}


def read(t, path):
    return t["read_file"].fn(path=path)


def edit(t, **args):
    return t["edit_file"].fn(**args)


def test_edit_requires_a_read_first(t):
    assert "haven't read 'cart.py' yet" in t["edit_file"].check(path="cart.py", old_string="qty", new_string="q")
    read(t, "cart.py")
    assert t["edit_file"].check(path="cart.py", old_string="price for", new_string="price * qty for") is None


def test_edit_applies_once_and_returns_a_diff(ws, t):
    read(t, "cart.py")
    out = edit(t, path="cart.py", old_string="sum(price for", new_string="sum(price * qty for")
    assert out.startswith("Edited cart.py: 1 replacement.")
    assert "-        return sum(price for _, price, qty in self.items)" in out
    assert "+        return sum(price * qty for _, price, qty in self.items)" in out
    assert "price * qty" in (ws.root / "cart.py").read_text(encoding="utf-8")
    # our own edit keeps the file "fresh": a second edit needs no re-read
    assert edit(t, path="cart.py", old_string="def subtotal", new_string="def sub_total").startswith("Edited")


def test_not_found_gives_the_closest_line(t):
    read(t, "cart.py")
    err = t["edit_file"].check(path="cart.py", old_string="  return sum(price for _, price in self.items)",
                               new_string="x")
    assert "was not found" in err
    assert "most similar line in the file is line 3" in err


def test_ambiguous_match_lists_lines_and_replace_all_works(ws, t):
    read(t, "dup.txt")
    err = t["edit_file"].check(path="dup.txt", old_string="x = 1", new_string="x = 3")
    assert "appears 2 times" in err and "(lines 1, 3)" in err
    assert edit(t, path="dup.txt", old_string="x = 1", new_string="x = 3", replace_all=True).startswith(
        "Edited dup.txt: 2 replacements.")
    assert (ws.root / "dup.txt").read_text(encoding="utf-8") == "x = 3\ny = 2\nx = 3\n"


def test_stale_file_is_refused_but_touch_alone_is_not(ws, t):
    read(t, "cart.py")
    p = ws.root / "cart.py"
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))   # only the timestamp changes
    assert t["edit_file"].check(path="cart.py", old_string="qty", new_string="q") is None
    p.write_text(CART + "# edited by the user\n", encoding="utf-8")    # real change
    assert "changed since you read it" in t["edit_file"].check(path="cart.py", old_string="qty", new_string="q")


def test_crlf_files_keep_their_line_endings(ws, t):
    read(t, "win.txt")
    edit(t, path="win.txt", old_string="one\ntwo", new_string="ONE\nTWO")
    assert (ws.root / "win.txt").read_bytes() == b"ONE\r\nTWO\r\nthree\r\n"


def test_copied_line_numbers_are_stripped(ws, t):
    read(t, "cart.py")
    out = edit(t, path="cart.py", old_string="     2\t    def subtotal(self):", new_string="     2\t    def subtotal(self) -> float:")
    assert out.startswith("Edited")
    assert "    def subtotal(self) -> float:\n" in (ws.root / "cart.py").read_text(encoding="utf-8")


def test_other_edit_errors(t):
    read(t, "cart.py")
    check = t["edit_file"].check
    assert "identical" in check(path="cart.py", old_string="a", new_string="a")
    assert "use write_file" in check(path="new.py", old_string="a", new_string="b")
    assert "old_string is empty" in check(path="cart.py", old_string="", new_string="b")


def test_write_creates_files_and_folders(ws, t):
    assert t["write_file"].check(path="pkg/new.py", content="x = 1\n") is None
    assert not t["write_file"].is_destructive({"path": "pkg/new.py"})
    assert t["write_file"].fn(path="pkg/new.py", content="x = 1\ny = 2\n") == "Created pkg/new.py (2 lines)."
    assert (ws.root / "pkg" / "new.py").read_bytes() == b"x = 1\ny = 2\n"


def test_overwrite_requires_a_read_and_is_destructive(ws, t):
    assert t["write_file"].is_destructive({"path": "cart.py"})
    assert "haven't read" in t["write_file"].check(path="cart.py", content="")
    with pytest.raises(EditError):
        t["write_file"].fn(path="cart.py", content="")
    read(t, "cart.py")
    out = t["write_file"].fn(path="cart.py", content="pass\n")
    assert out.startswith("Overwrote cart.py (1 line, was 3).")


def test_previews_are_diffs(t):
    read(t, "cart.py")
    diff = t["edit_file"].preview(path="cart.py", old_string="subtotal", new_string="sub")
    assert diff.splitlines()[:2] == ["--- a/cart.py", "+++ b/cart.py"]
    assert t["write_file"].preview(path="new.txt", content="a\nb\n") == "new file new.txt (2 lines)\n+a\n+b"


def test_agent_never_asks_to_approve_a_doomed_edit(ws, t):
    asked = []
    provider = ScriptedProvider([calls(call("edit_file", path="cart.py", old_string="nope", new_string="x")),
                                 final("ok")])
    agent = Agent(provider, list(t.values()), "s", approve=lambda c, tool: asked.append(c) or True)
    agent.run("edit")
    assert asked == []                                               # the check failed first
    assert "haven't read" in [m.content for m in agent.messages if m.role == "tool"][0]
