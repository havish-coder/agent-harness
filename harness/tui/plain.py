"""Lessons 07-21: the plain terminal interface: ANSI colours and print(), no extra libraries.

Used when output isn't a terminal (pipes, logs, tests), when `rich` isn't installed, or with
`--plain`. The rich interface (Lesson 22) implements the same three things: an event handler,
an approver and a few messages.
"""
import os
from contextlib import nullcontext

DIM, CYAN, BOLD, YELLOW, RESET = "\033[2m", "\033[36m", "\033[1m", "\033[33m", "\033[0m"


def enable_ansi() -> None:
    if os.name == "nt":
        os.system("")  # makes old Windows consoles understand ANSI colour codes


class PlainUI:
    """Prints the agent's events as they happen, including streamed text."""

    def __init__(self):
        self.mid_line = False      # inside a streamed line that hasn't ended yet
        self.current = ""          # text streamed for the reply in progress
        self.last_streamed = ""    # text streamed for the last complete reply

    # --- events -----------------------------------------------------------------------------
    def end_line(self):
        if self.mid_line:
            print()
            self.mid_line = False

    def __call__(self, kind, data):
        if kind == "thinking_delta":
            if not self.mid_line:
                print(f"{DIM}  (thinking) ", end="")
            print(f"{DIM}{data}{RESET}", end="", flush=True)
            self.mid_line = True
        elif kind == "text_delta":
            if not self.current:
                self.end_line()
                print(f"\n{BOLD}agent>{RESET} ", end="")
            print(data, end="", flush=True)
            self.current += data
            self.mid_line = True
        elif kind == "model_reply":
            self.end_line()
            self.last_streamed, self.current = self.current, ""
        elif kind == "tool_call":
            self.end_line()
            args = ", ".join(f"{k}={v!r}" for k, v in data.arguments.items())
            print(f"{CYAN}  → {data.name}({args}){RESET}")
        elif kind == "tool_denied":
            print(f"{DIM}    (denied){RESET}")
        elif kind == "tool_result":
            _, result = data
            preview = result if len(result) <= 300 else result[:300] + " …"
            print(DIM + "    " + preview.replace("\n", "\n    ") + RESET)

    # --- messages from the app ----------------------------------------------------------------
    def answer(self, text: str):
        """Print the final answer, unless it was already streamed to the screen."""
        self.end_line()
        if text.strip() != self.last_streamed.strip():
            print(f"\n{BOLD}agent>{RESET} {text}")
        self.last_streamed = ""

    def retry(self, notice):
        """Called by RetryingProvider before it waits and tries again."""
        self.end_line()
        if notice.fallback:
            print(f"{YELLOW}  ! {notice.error} — switching to the fallback model{RESET}")
        else:
            print(f"{YELLOW}  ! {notice.error} — retrying in {notice.delay:.1f} s (retry {notice.attempt}){RESET}")

    def info(self, text: str):
        print(f"{DIM}{text}{RESET}")

    def warn(self, text: str):
        self.end_line()
        print(f"{YELLOW}{text}{RESET}")

    def error(self, text: str):
        self.end_line()
        print(f"error: {text}")

    def banner(self, title: str, details: str):
        print(f"{BOLD}{title}{RESET} · {details}")

    def usage_line(self, text: str):
        print(f"{DIM}  [{text}]{RESET}")

    def read_input(self, prompt: str = "you> ") -> str:
        return input(f"\n{BOLD}{prompt}{RESET}")


class PlainApprover:
    """Asks before any tool call that can change things. 'a' = always allow this tool."""

    def __init__(self, auto_approve: bool = False, ui: PlainUI | None = None):
        self.auto_approve = auto_approve
        self.always: set[str] = set()   # tool names allowed for the rest of the session
        self.pause = nullcontext        # replaced by KeyWatcher.paused, so the prompt gets the keys

    def show(self, call, tool):
        warning = " (may destroy data)" if tool.is_destructive(call.arguments) else ""
        print(f"{YELLOW}  ? {tool.name} wants to run{warning}{RESET}")
        if tool.preview:
            try:
                print(DIM + "    " + tool.preview(**call.arguments).replace("\n", "\n    ") + RESET)
            except Exception as e:
                print(f"{DIM}    (no preview: {e}){RESET}")

    def ask(self, tool_name: str) -> str:
        return input(f"{YELLOW}    allow? [y]es / [n]o / [a]lways for {tool_name}: {RESET}")

    def __call__(self, call, tool) -> bool:
        if self.auto_approve or tool.name in self.always:
            return True
        with self.pause():
            self.show(call, tool)
            while True:
                answer = self.ask(tool.name).strip().lower()
                if answer in ("y", "yes"):
                    return True
                if answer in ("n", "no", ""):
                    return False
                if answer in ("a", "always"):
                    self.always.add(tool.name)
                    return True
