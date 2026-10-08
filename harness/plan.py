"""Lesson 45: plan mode. Look first, then propose, then wait for a yes.

Permission mode `plan` (Lesson 29) already makes every tool that changes something refuse: the agent can read, search and think, nothing more. What it
lacked was the way out. A model that has finished looking has nowhere to put its plan except its answer, and nothing for the user to approve.

    /plan             turn plan mode on (or `--mode plan` at start)
    ...the agent reads, then calls exit_plan_mode(plan="1. ... 2. ...")
    the plan is shown, and the user chooses:
        [y] yes, ask me before each change      -> mode "default"
        [a] yes, and accept file edits          -> mode "accept-edits"
        [n] no, keep planning
        [f] no, and I'll say what to change     -> the user's words go back to the model

Three properties carry the weight, and none of them depends on the model:
  * **The refusal is the permission layer's**, not a request in a prompt. In plan mode a write_file call is denied however the model was persuaded.
  * **Only the user's answer changes the mode.** `exit_plan_mode` is read-only for permissions (so plan mode allows it) but it does nothing itself: it shows
    the plan and asks, and the harness switches the mode when the user says yes. The model has no tool that leaves plan mode on its own say-so.
  * **The tool exists only in plan mode** (`Tool.enabled`): outside it the model isn't told about it and can't call it.

An approved plan is saved in the user's folder (not in the project), and its numbered steps start the todo list (Lesson 44), because a model that has just
written six steps has no excuse to need a second tool call to write them again, and the harness can parse them without asking the model to.
"""
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from harness.todo import MAX_ITEMS, TodoItem, clean
from harness.tools.base import Tool, tool

PLAN_RULE = ("You are in plan mode. You can read and search, and you cannot change anything. Look at what you need to, then call exit_plan_mode with your plan: "
             "a one-line goal, numbered steps that each name the file and the change, and anything you are unsure of. "
             "Do not write the plan as your answer instead: the user can only approve it through exit_plan_mode.")
CHOICES = {"y": "yes, ask me before each change", "a": "yes, and accept file edits", "n": "no, keep planning", "f": "no, I'll say what to change"}
MIN_PLAN_CHARS = 20
MAX_PLAN_CHARS = 8_000
STEP = re.compile(r"^\s{0,3}\d{1,2}[.)]\s+(\S.*?)\s*$")        # a numbered line at the left margin: "1. Edit cart.py"


def steps(plan: str) -> list[str]:
    """The numbered steps of a plan, one line each, cleaned for display. Lines indented under a step are its detail, not steps."""
    found = [clean(m.group(1)) for line in plan.splitlines() if (m := STEP.match(line))]
    return [s for s in found if s][:MAX_ITEMS]


def plan_items(plan: str) -> list[TodoItem]:
    """The steps as a todo list: the first one in progress."""
    items = [TodoItem(s, "pending") for s in steps(plan)]
    if items:
        items[0].status = "in_progress"
    return items


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "plan"


def title_of(plan: str) -> str:
    """A name for the plan's file: its first heading, or its first line."""
    for line in plan.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line
    return "plan"


def save_plan(directory: Path, plan: str) -> Path:
    """Write an approved plan to `directory` (in the user's folder). The name starts with the time, so the newest sorts last."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{datetime.now():%Y%m%d-%H%M%S}-{slug(title_of(plan))}.md"
    path.write_text(plan.rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass                                              # Windows and some file systems: the folder's own permissions apply
    return path


def latest_plan(directory: Path) -> tuple[Path, str] | None:
    """The newest saved plan, or None."""
    files = sorted(directory.glob("*.md")) if directory.is_dir() else []
    if not files:
        return None
    return files[-1], files[-1].read_text(encoding="utf-8", errors="replace")


def age(path: Path) -> str:
    seconds = time.time() - path.stat().st_mtime
    return f"{int(seconds // 60)} min ago" if seconds < 3_600 else f"{int(seconds // 3_600)} h ago" if seconds < 86_400 else f"{int(seconds // 86_400)} days ago"


def make_plan_tools(review: Callable[[str], str], enabled: Callable[[], bool]) -> list[Tool]:
    """`exit_plan_mode(plan)`: show the plan to the user and report their answer. `review` does the asking (the session's)."""

    @tool(read_only=True, concurrency_safe=False, enabled=enabled)
    def exit_plan_mode(plan: str) -> str:
        """Give the user your plan to approve, when you have finished looking. Nothing can change until they say yes.
        Markdown: a one-line goal, numbered steps that each name the file and the change, then anything you are unsure of.

        Args:
            plan: the whole plan.
        """
        return review(plan)

    return [exit_plan_mode]
