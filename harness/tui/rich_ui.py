"""Lesson 22: a richer terminal: Markdown answers rendered as they stream, highlighted diffs,
compact tool lines, and a spinner while the model is thinking.

Built on `rich` (an optional dependency, ADR 0002). Same interface as PlainUI, so the app
doesn't care which one it got.
"""
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.markup import escape
from rich.padding import Padding
from rich.syntax import Syntax
from rich.text import Text

from harness.security.permissions import CHANGES
from harness.tui.latex import render_math
from harness.tui.plain import PlainApprover

TOOL_RESULT_LINES = 4       # lines of a tool result shown under the call


def short_args(arguments: dict, width: int = 70) -> str:
    """read_file(path='a.py') style, with long values cut so one call fits on one line."""
    parts = []
    for key, value in arguments.items():
        shown = repr(value)
        if len(shown) > 40:
            shown = shown[:37] + "…'"
        parts.append(f"{key}={shown}")
    text = ", ".join(parts)
    return text if len(text) <= width else text[: width - 1] + "…"


class RichUI:
    def __init__(self, console: Console | None = None, spinner: bool = True):
        self.console = console or Console(highlight=False)
        self.spinner = spinner               # off for recordings and screenshots
        self.live: Live | None = None        # the answer being streamed, rendered as Markdown
        self.status = None                   # the "thinking" spinner
        self.current = ""
        self.last_streamed = ""
        self.thinking = False

    @staticmethod
    def markdown(text: str) -> Markdown:
        """An answer as rich Markdown, with LaTeX math shown as Unicode (Lesson 25b)."""
        return Markdown(render_math(text))

    # --- the two live regions: never more than one at a time ---------------------------------
    def stop_spinner(self):
        if self.status is not None:
            self.status.stop()
            self.status = None

    def start_spinner(self, text: str = "Thinking…"):
        self.stop_live()
        if self.spinner and self.status is None and self.console.is_terminal:
            self.status = self.console.status(f"[dim]{text}[/dim]", spinner="dots")
            self.status.start()

    def stop_live(self):
        if self.live is not None:
            self.live.stop()
            self.live = None

    def end_thinking(self):
        if self.thinking:
            self.console.print()
            self.thinking = False

    # --- events -------------------------------------------------------------------------------
    def __call__(self, kind, data):
        if kind == "model_call":
            self.start_spinner()
        elif kind == "thinking_delta":
            self.stop_spinner()
            if not self.thinking:
                self.console.print(Text("✻ ", style="dim"), end="")
                self.thinking = True
            self.console.print(Text(data, style="dim italic"), end="")
        elif kind == "text_delta":
            self.stop_spinner()
            self.end_thinking()
            self.current += data
            if self.live is None:
                self.console.print()                 # a blank line before the answer
                self.live = Live(self.markdown(self.current), console=self.console, refresh_per_second=10,
                                 vertical_overflow="visible", transient=False)
                self.live.start()
            else:
                self.live.update(self.markdown(self.current))
        elif kind == "model_reply":
            self.stop_spinner()
            self.end_thinking()
            if self.live is not None:
                self.live.update(self.markdown(self.current))
                self.stop_live()
            self.last_streamed, self.current = self.current, ""
        elif kind == "tool_call":
            self.stop_spinner()
            self.stop_live()
            line = Text("● ", style="cyan")
            line.append(data.name, style="bold cyan")
            line.append(f"({short_args(data.arguments)})", style="cyan")
            self.console.print(line)
        elif kind == "tool_denied":
            self.console.print(Text("  └ denied", style="yellow"))
        elif kind == "tool_result":
            call, result = data
            lines = result.splitlines() or ["(empty)"]
            if call.name in ("edit_file", "write_file") and not result.startswith("Error"):
                lines = shown = lines[:1]            # the diff was already shown when approving
            elif call.name == "run_shell" and len(lines) > TOOL_RESULT_LINES:
                shown = [lines[0], "…", *lines[-(TOOL_RESULT_LINES - 1):]]   # status + the end (summaries)
            else:
                shown = lines[:TOOL_RESULT_LINES]
            hidden = len(lines) - len([line for line in shown if line != "…"])
            more = f"  … {hidden} more lines" if hidden > 0 and "…" not in shown else ""
            style = "red" if result.startswith("Error") else "dim"
            body = Text("\n".join(line[:200] for line in shown) + more, style=style)
            self.console.print(Padding(Text("└ ", style="dim") + body, (0, 0, 0, 2)))

    # --- messages from the app ----------------------------------------------------------------
    def answer(self, text: str):
        self.stop_spinner()
        self.stop_live()
        if text.strip() != self.last_streamed.strip():
            self.console.print()
            self.console.print(self.markdown(text))
        self.last_streamed = ""

    def retry(self, notice):
        self.stop_spinner()
        self.stop_live()
        if notice.fallback:
            self.console.print(f"[yellow]! {notice.error} — switching to the fallback model[/yellow]")
        else:
            self.console.print(f"[yellow]! {notice.error} — retrying in {notice.delay:.1f} s "
                               f"(retry {notice.attempt})[/yellow]")

    def info(self, text: str):
        self.console.print(Text(text, style="dim"))

    def warn(self, text: str):
        self.console.print(Text(text, style="yellow"))

    def error(self, text: str):
        self.stop_spinner()
        self.stop_live()
        self.console.print(Text(f"error: {text}", style="bold red"))

    def banner(self, title: str, details: str):
        self.console.rule(Text(title, style="bold"), style="dim")
        self.console.print(Text(details, style="dim"), justify="center")

    def usage_line(self, text: str):
        self.console.print(Text(f"  {text}", style="dim"))

    def read_input(self, prompt: str = "you> ") -> str:
        self.console.print()
        return self.console.input(f"[bold]{prompt}[/bold]")


class RichApprover(PlainApprover):
    """The same y/n/always answers as PlainApprover, with a highlighted diff."""

    def __init__(self, ui: RichUI | None = None):
        super().__init__()
        self.console = ui.console if ui else Console()

    def show(self, call, tool, reason: str | None = None):
        destructive = tool.is_destructive(call.arguments)
        title = Text("? ", style="yellow")
        title.append(f"{tool.name}", style="bold yellow")
        title.append(" wants to run", style="yellow")
        if destructive:
            title.append(" (may destroy data)", style="bold red")
        self.console.print(title)
        if reason and reason != CHANGES:
            self.console.print(Text(f"  asking because {reason}", style="yellow"))
        if call.name == "run_shell":
            self.console.print(Padding(Syntax(call.arguments.get("command", ""), "bash", theme="ansi_dark",
                                              word_wrap=True), (0, 0, 0, 2)))
        if tool.preview:
            try:
                preview = tool.preview(**call.arguments)
                lexer = "diff" if preview.startswith(("---", "new file")) else "text"
                self.console.print(Padding(Syntax(preview, lexer, theme="ansi_dark", word_wrap=True), (0, 0, 0, 2)))
            except Exception as e:
                self.console.print(Text(f"  (no preview: {e})", style="dim"))

    def ask(self, always: str | None) -> str:
        return self.console.input(f"  [yellow]allow? {options_markup(always)}: [/yellow]")


def options_markup(always: str | None) -> str:
    options = "[bold]y[/bold]es / [bold]n[/bold]o"
    if always:
        options += f" / [bold]a[/bold]lways allow {escape(always)} (this session)"
    return options
