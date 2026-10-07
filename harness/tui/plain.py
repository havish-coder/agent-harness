"""Lessons 07-21: the plain terminal interface: ANSI colours and print(), no extra libraries.

Used when output isn't a terminal (pipes, logs, tests), when `rich` isn't installed, or with
`--plain`. The rich interface (Lesson 22) implements the same three things: an event handler,
an approver and a few messages.
"""
import os
from contextlib import nullcontext

from harness.security.permissions import CHANGES

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
        elif kind == "microcompact":
            self.end_line()
            print(f"{DIM}  (the window is filling: cleared {len(data.cleared)} old result"
                  f"{'s' if len(data.cleared) != 1 else ''}, ~{data.saved:,} tokens){RESET}")
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


def always_label(decision) -> str | None:
    """What [a]lways would allow, in words, or None when "always" isn't offered (Lesson 29)."""
    rule = decision.remember if decision is not None else None
    if rule is None:
        return None
    return "this exact command" if rule.exact else f"every {rule.tool} call" if rule.pattern is None else str(rule)


class PlainApprover:
    """Asks the user about a call the permissions sent to "ask" (Lesson 29). Answers True, False,
    or "always": run it and add the decision's suggested rule for the rest of the session. Which
    calls get here, and what "always" remembers, is decided by harness/security/permissions.py."""

    def __init__(self, ui: PlainUI | None = None):
        self.pause = nullcontext        # replaced by KeyWatcher.paused, so the prompt gets the keys

    def show(self, call, tool, reason: str | None = None, notes=()):
        warning = " (may destroy data)" if tool.is_destructive(call.arguments) else ""
        print(f"{YELLOW}  ? {tool.name} wants to run{warning}{RESET}")
        if reason and reason != CHANGES:
            print(f"{YELLOW}    asking because {reason}{RESET}")
        for note in notes:
            print(f"{YELLOW}    ! {note}{RESET}")
        if tool.preview:
            try:
                print(DIM + "    " + tool.preview(**call.arguments).replace("\n", "\n    ") + RESET)
            except Exception as e:
                print(f"{DIM}    (no preview: {e}){RESET}")

    def ask(self, always: str | None) -> str:
        options = "[y]es / [n]o" + (f" / [a]lways allow {always} (this session)" if always else "")
        return input(f"{YELLOW}    allow? {options}: {RESET}")

    def __call__(self, call, tool, decision=None) -> bool | str:
        always = always_label(decision)
        with self.pause():
            self.show(call, tool, decision.reason if decision else None, decision.notes if decision else ())
            while True:
                answer = self.ask(always).strip().lower()
                if answer in ("y", "yes"):
                    return True
                if answer in ("n", "no", ""):
                    return False
                if always and answer in ("a", "always"):
                    return "always"
