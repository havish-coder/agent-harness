"""Render docs/images/demo.svg: the recorded bug-fix run, replayed through the rich terminal UI.

Run:  python scripts/render_demo.py

No model needed: the model's replies come from tests/cassettes/fix_subtotal.jsonl and the
real tools run on a temporary copy of workspace/, so the picture is reproducible.
"""
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console  # noqa: E402

from harness.agent import Agent  # noqa: E402
from harness.cli import SYSTEM_PROMPT  # noqa: E402
from harness.providers.fake import ReplayProvider, committed_copy  # noqa: E402
from harness.tools import default_tools  # noqa: E402
from harness.tools.fs import workspace_snapshot  # noqa: E402
from harness.tui.rich_ui import RichApprover, RichUI  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

CASSETTE = ROOT / "tests" / "cassettes" / "fix_subtotal.jsonl"


class DemoApprover(RichApprover):
    """Shows the real approval prompt, then answers 'y' as a user would."""

    def ask(self, tool_name: str) -> str:
        self.console.print(f"  [yellow]allow? [bold]y[/bold]es / [bold]n[/bold]o / [bold]a[/bold]lways "
                           f"for {tool_name}:[/yellow] y")
        return "y"


def main() -> None:
    root = Path(tempfile.mkdtemp()) / "ws"
    committed_copy(ROOT, "workspace", root)
    console = Console(file=io.StringIO(), record=True, force_terminal=True, width=96,
                      color_system="truecolor", legacy_windows=False)   # record only, print nothing
    ui = RichUI(console, spinner=False)
    ws = Workspace(root)
    task = next(m["content"] for m in json.loads(CASSETTE.read_text(encoding="utf-8").splitlines()[0])["request"]
                if m["role"] == "user")
    agent = Agent(ReplayProvider(CASSETTE, root=root), default_tools(ws),
                  SYSTEM_PROMPT.format(snapshot=workspace_snapshot(ws)), max_steps=20, on_event=ui,
                  approve=DemoApprover(ui=ui))
    ui.banner("Agent harness", "ollama · qwen3:4b-instruct · workspace")
    console.print(f"\n[bold]you>[/bold] {task}")
    ui.answer(agent.run(task))
    out = ROOT / "docs" / "images" / "demo.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(out), title="harness")
    print(f"saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
