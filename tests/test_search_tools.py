"""Lesson 11: glob and grep."""
import os
import time

import pytest

from harness.tools.search import GLOB_LIMIT, _matches_glob, make_search_tools
from harness.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    files = {
        "README.md": "# Demo\nTODO: write docs\n",
        "src/app.py": "def total(items):\n    return sum(items)  # TODO: rounding\n\n\ndef main():\n    print(total([1, 2]))\n",
        "src/util/helpers.py": "def helper():\n    pass\n",
        "tests/test_app.py": "from app import total\n\ndef test_total():\n    assert total([1]) == 1\n",
        "node_modules/lib/index.js": "TODO: should never be searched\n",
        ".git/config": "TODO: never\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\0TODO")
    old = time.time() - 3600
    os.utime(tmp_path / "README.md", (old, old))   # oldest file
    return Workspace(tmp_path)


@pytest.fixture
def tools(ws):
    return {t.name: t.fn for t in make_search_tools(ws)}


@pytest.mark.parametrize("rel,pattern,expected", [
    ("src/app.py", "*.py", True),                 # bare pattern: any folder
    ("src/app.py", "src/*.py", True),
    ("src/util/helpers.py", "src/**/*.py", True),
    ("src/app.py", "src/**/*.py", True),          # ** may match zero folders
    ("app.py", "**/*.py", True),
    ("src/app.py", "tests/*.py", False),
    ("README.md", "*.py", False),
])
def test_glob_matching(rel, pattern, expected):
    assert _matches_glob(rel, pattern) is expected


def test_glob_newest_first_and_skips_ignored(tools, ws):
    out = tools["glob"](pattern="*")
    lines = out.splitlines()
    assert lines[-1] == "README.md"                 # oldest last
    assert not any("node_modules" in line or ".git" in line for line in lines)
    assert tools["glob"](pattern="*.rs") == "No files match '*.rs' in ./."


def test_glob_caps_results(ws, tools):
    for i in range(GLOB_LIMIT + 5):
        (ws.root / f"gen_{i}.txt").write_text("", encoding="utf-8")
    out = tools["glob"](pattern="gen_*.txt")
    assert out.endswith("... and 5 more. Use a more specific pattern or path.")


def test_grep_lines_with_counts(tools):
    out = tools["grep"](pattern="TODO")
    assert out.splitlines() == [
        "README.md:2: TODO: write docs",
        "src/app.py:2:     return sum(items)  # TODO: rounding",
        "(2 matches in 2 files)",
    ]   # node_modules, .git and the binary logo.png are skipped


def test_grep_modes_glob_and_case(tools):
    assert tools["grep"](pattern="def ", output="files", glob="*.py").splitlines()[:3] == [
        "src/app.py", "src/util/helpers.py", "tests/test_app.py"]
    assert tools["grep"](pattern="total", output="count").splitlines()[:2] == ["src/app.py: 2", "tests/test_app.py: 3"]
    assert "No matches" in tools["grep"](pattern="todo")
    assert "README.md:2:" in tools["grep"](pattern="todo", ignore_case=True)


def test_grep_context(tools):
    out = tools["grep"](pattern="def main", context=1, path="src/app.py")
    assert out.splitlines()[:3] == ["src/app.py-4- ", "src/app.py:5: def main():", "src/app.py-6-     print(total([1, 2]))"]


def test_grep_invalid_regex_falls_back_to_plain_text(tools):
    out = tools["grep"](pattern="total([1")
    assert out.startswith("(not a valid regular expression")
    assert "src/app.py:6:" in out


def test_grep_limit(tools):
    out = tools["grep"](pattern="t", limit=3)
    assert len(out.splitlines()) == 4 and "showing the first 3 lines" in out


def test_grep_context_groups_are_merged_like_grep(ws, tools):
    (ws.root / "c.txt").write_text("a\nX\nb\nc\nX\nd\ne\nf\ng\nX\n", encoding="utf-8")
    out = tools["grep"](pattern="X", path="c.txt", context=1).splitlines()
    assert out == ["c.txt-1- a", "c.txt:2: X", "c.txt-3- b", "c.txt-4- c", "c.txt:5: X", "c.txt-6- d",
                   "--", "c.txt-9- g", "c.txt:10: X", "(3 matches in 1 file)"]
