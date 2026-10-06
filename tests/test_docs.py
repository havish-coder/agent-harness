"""The documentation is part of the product: a broken link fails the build."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_docs", Path(__file__).resolve().parent.parent / "scripts" / "check_docs.py")
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)


def test_no_broken_links():
    assert check_docs.broken_links() == []


def test_checker_finds_a_broken_link(tmp_path):
    (tmp_path / "a.md").write_text("see [b](b.md) and [c](c.md#nope)\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("# Hello\n", encoding="utf-8")
    problems = check_docs.broken_links(tmp_path)
    assert len(problems) == 2
    assert "missing file" in problems[0] or "missing file" in problems[1]
