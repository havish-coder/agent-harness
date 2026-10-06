"""Lesson 25b: exporting chats as Markdown, LaTeX and PDF."""
import pytest

from harness import export as ex
from harness.export import ExportError, chat_markdown, export, find_tool, for_latex
from harness.messages import Message, ToolCall

CHAT = [
    Message.system("system prompt"),
    Message.user("Sum 1..n? see @notes.txt\n\nThe user attached these with @ (already read):\n<file>secret</file>"),
    Message("assistant", "Let me check.", tool_calls=[ToolCall("1", "read_file", {"path": "notes.txt"})]),
    Message.tool_result(ToolCall("1", "read_file", {}), "TODO: buy milk"),
    Message("assistant", "It is $\\frac{n(n+1)}{2}$ ✓"),
]


def test_chat_markdown():
    md = chat_markdown(CHAT, "Sum", "qwen3:4b-instruct")
    assert md.startswith('---\ntitle: "Sum"\nsubtitle: "qwen3:4b-instruct"\ndate: "')
    assert "## You\n\nSum 1..n? see @notes.txt\n" in md and "secret" not in md   # attachments left out
    assert "> *used* `read_file(path='notes.txt')`" in md
    assert "TODO: buy milk" not in md                                            # tool results left out
    assert md.count("## Agent") == 2 and "system prompt" not in md
    last = chat_markdown(CHAT, "Sum", "m", last_only=True)
    assert "## You" not in last and last.count("## Agent") == 1 and "frac" in last


def test_for_latex_replaces_glyphs_our_fonts_lack():
    assert for_latex("done ✓") == "done $\\checkmark$"


def test_markdown_always_works(tmp_path):
    out = export("# hi\n", "md", tmp_path / "chat")
    assert out.name == "chat.md" and out.read_text(encoding="utf-8") == "# hi\n"


def test_missing_tools_fall_back(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "find_tool", lambda name: None)
    with pytest.raises(ExportError, match="pandoc isn't installed, so I wrote chat.md"):
        export("# hi\n", "pdf", tmp_path / "chat")
    assert (tmp_path / "chat.md").exists()


def test_find_tool_looks_in_harness_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "USER_DIR", tmp_path)
    monkeypatch.setattr(ex.shutil, "which", lambda name: None)
    exe = tmp_path / "tools" / "pandoc-9.9" / "pandoc.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert find_tool("pandoc") == exe and find_tool("tectonic") is None


@pytest.mark.live
def test_real_tex_and_pdf(tmp_path):
    if find_tool("pandoc") is None or find_tool("tectonic") is None:
        pytest.skip("pandoc and Tectonic are not installed")
    md = chat_markdown(CHAT, "Sum", "qwen3:4b-instruct")
    tex = export(md, "tex", tmp_path / "chat").read_text(encoding="utf-8")
    assert "\\begin{document}" in tex and "\\frac{n(n+1)}{2}" in tex and "\\checkmark" in tex
    pdf = export(md, "pdf", tmp_path / "chat").read_bytes()
    assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF") and len(pdf) > 5_000
