"""Lesson 22: the rich terminal UI, rendered into a recording console."""
import io

from rich.console import Console

from harness.messages import Message, Reply, ToolCall, Usage
from harness.tools.base import tool
from harness.tui.rich_ui import RichApprover, RichUI, short_args


def ui(width=80):
    console = Console(file=io.StringIO(), record=True, force_terminal=True, width=width,
                      color_system=None, legacy_windows=False)
    return RichUI(console, spinner=False), console


def test_streamed_markdown_is_rendered_and_not_printed_twice():
    r, console = ui()
    for piece in ["# Fixed\n\n", "The **subtotal** now ", "multiplies by `qty`."]:
        r("text_delta", piece)
    r("model_reply", Reply(Message("assistant", "x"), "end", Usage()))
    r.answer("# Fixed\n\nThe **subtotal** now multiplies by `qty`.")
    text = console.export_text()
    assert "Fixed" in text and "# Fixed" not in text          # a heading, not raw Markdown
    assert "**" not in text
    assert text.count("multiplies by qty") == 1                # streamed once, not repeated by answer()


def test_tool_calls_and_results_are_compact():
    r, console = ui()
    call = ToolCall("1", "read_file", {"path": "project/shop/cart.py"})
    r("tool_call", call)
    r("tool_result", (call, "\n".join(f"line {i}" for i in range(20))))
    r("tool_result", (call, "Error: FileNotFoundError: no file named 'x'"))
    text = console.export_text()
    assert "● read_file(path='project/shop/cart.py')" in text
    assert "└ line 0" in text and "line 3" in text and "line 4" not in text
    assert "16 more lines" in text and "Error: FileNotFoundError" in text


def test_short_args_cuts_long_values():
    out = short_args({"path": "a.py", "old_string": "x" * 200})
    assert out.startswith("path='a.py', old_string='xxx") and len(out) <= 70


def test_approver_shows_a_highlighted_diff_and_the_command():
    @tool
    def edit(path: str) -> str:
        """Edit."""
        return ""
    edit.preview = lambda path: "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new"
    r, console = ui()
    approver = RichApprover(ui=r)
    approver.show(ToolCall("1", "edit", {"path": "x"}), edit)

    @tool
    def run_shell(command: str) -> str:
        """Run."""
        return ""
    approver.show(ToolCall("2", "run_shell", {"command": "python -m pytest -q"}), run_shell)
    text = console.export_text()
    assert "? edit wants to run" in text and "-old" in text and "+new" in text
    assert "python -m pytest -q" in text
