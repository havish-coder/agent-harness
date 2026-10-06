"""Lesson 10: read_file returns numbered, bounded, honest output."""
import pytest

from harness.tools import fs
from harness.tools.fs import UNCHANGED, make_fs_tools, workspace_snapshot
from harness.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (tmp_path / "big.log").write_text("".join(f"line {i}\n" for i in range(1, 2001)), encoding="utf-8")
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x89PNG\0\0\0data")
    (tmp_path / "latin1.txt").write_bytes("caf\xe9\n".encode("latin-1"))
    (tmp_path / "crlf.txt").write_bytes(b"one\r\ntwo\r\n")
    (tmp_path / "src").mkdir()
    (tmp_path / ".git").mkdir()
    return Workspace(tmp_path)


@pytest.fixture
def tools(ws):
    return {t.name: t for t in make_fs_tools(ws)}


def read(tools, **args):
    return tools["read_file"].fn(**args)


def test_numbered_lines_with_a_header(tools):
    assert read(tools, path="notes.txt") == (
        "notes.txt: lines 1-3 of 3\n     1\talpha\n     2\tbeta\n     3\tgamma")


def test_offset_and_limit(tools):
    out = read(tools, path="big.log", offset=1500, limit=2)
    assert out.splitlines() == ["big.log: lines 1500-1501 of 2000. More below: read_file(path='big.log', offset=1502)",
                                "  1500\tline 1500", "  1501\tline 1501"]


def test_long_files_stop_at_the_budget_and_say_how_to_continue(tools):
    out = read(tools, path="big.log")
    first = out.splitlines()[0]
    assert first.startswith("big.log: lines 1-300 of 2000. More below") and "offset=301" in first
    assert len(out) <= fs.READ_BUDGET_CHARS + 200


def test_long_lines_are_cut(ws, tools):
    (ws.root / "min.js").write_text("x" * 5000, encoding="utf-8")
    out = read(tools, path="min.js")
    assert "[line cut: 5,000 chars]" in out and len(out) < 700


def test_edge_cases(tools):
    assert read(tools, path="empty.txt") == "(empty.txt is empty)"
    assert read(tools, path="notes.txt", offset=10) == (
        "(offset 10 is past the end: notes.txt has 3 lines; the last line is offset=3, or use offset=-1)")
    assert "(not valid UTF-8" in read(tools, path="latin1.txt")
    assert read(tools, path="crlf.txt").endswith("     1\tone\n     2\ttwo")
    with pytest.raises(ValueError, match="binary file"):
        read(tools, path="blob.bin")
    with pytest.raises(IsADirectoryError, match="use list_dir"):
        read(tools, path="src")
    with pytest.raises(FileNotFoundError, match=r"Did you mean: notes\.txt\?"):
        read(tools, path="note.txt")
    with pytest.raises(ValueError, match="limit must be at least 1"):
        read(tools, path="notes.txt", limit=0)


def test_zero_and_negative_offsets(tools):
    assert read(tools, path="notes.txt", offset=0, limit=1).endswith("     1\talpha")
    assert read(tools, path="big.log", offset=-2).splitlines() == [
        "big.log: lines 1999-2000 of 2000", "  1999\tline 1999", "  2000\tline 2000"]
    assert read(tools, path="notes.txt", offset=-99).startswith("notes.txt: lines 1-3")


def test_rereading_an_unchanged_range_returns_a_stub(ws, tools):
    first = read(tools, path="notes.txt")
    assert read(tools, path="notes.txt") == UNCHANGED
    assert read(tools, path="notes.txt", offset=2) != UNCHANGED      # a different range is new
    (ws.root / "notes.txt").write_text("changed\n", encoding="utf-8")
    assert read(tools, path="notes.txt") != first                    # file changed → fresh content
    ws.forget_reads()
    assert read(tools, path="notes.txt") != UNCHANGED                # after a reset → fresh content


def test_list_dir_errors(tools):
    with pytest.raises(NotADirectoryError, match="use read_file"):
        tools["list_dir"].fn(path="notes.txt")
    with pytest.raises(FileNotFoundError, match="no folder named 'srcs'"):
        tools["list_dir"].fn(path="srcs")


def test_snapshot_skips_ignored_folders(ws):
    snap = workspace_snapshot(ws)
    assert "src/" in snap and ".git" not in snap
