"""Lesson 44: a todo list the agent keeps for itself.

A small model given "rename this function everywhere, update the tests and the README" tends to do the first part, say "Done!", and stop. A list
helps in two ways: it is written in the conversation, so it is in front of the model on every later call; and the harness can see it, so
when the model tries to finish while items are still open, the harness can say so (a *nudge*, capped at two per request).

    todo_write(todos=[{"content": "Rename the function", "status": "in_progress"}, {"content": "Update the tests", "status": "pending"}])

The model sends the **whole list** each time (a replace, not "add item"): there is nothing to get out of step with, and the latest call is the
state. That also means the state can always be **rebuilt from the conversation**: after a resume, a fork or a rewind, the list is whatever the
last `todo_write` call still in the conversation said (`from_messages`). Nothing is stored beside the chat log.

The tool changes nothing outside the harness (no file, no command), so it is read-only for permissions and never asks.

Whose words (the rule of Lessons 39, 42 and 42b): the items are the model's, and may have been written after it read a web page. A list written
then is marked, and when the harness quotes it back to the model (in a nudge, or in a summary) it is fenced as information, not as the
user's instructions. And every item the model acts on still goes through the usual permission rules.
"""
import re
from dataclasses import dataclass, field

from harness.messages import Message
from harness.security.taint import Taint, fence
from harness.tools.base import Tool, tool

STATUSES = ("pending", "in_progress", "completed")
MARKS = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
MAX_ITEMS = 20
MAX_CHARS = 120
# What small models write instead of the three words. Accepting them costs nothing; refusing them costs a round trip each.
ALIASES = {"in progress": "in_progress", "in-progress": "in_progress", "inprogress": "in_progress", "doing": "in_progress",
           "active": "in_progress", "current": "in_progress", "started": "in_progress",
           "done": "completed", "complete": "completed", "finished": "completed", "complete.": "completed",
           "todo": "pending", "to do": "pending", "not started": "pending", "open": "pending", "not_started": "pending"}
TOOL_NAME = "todo_write"
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class TodoError(ValueError):
    """The list can't be accepted; the message is written for the model."""


@dataclass
class TodoItem:
    content: str
    status: str = "pending"


@dataclass
class TodoList:
    items: list[TodoItem] = field(default_factory=list)
    tainted: bool = False                              # written after untrusted content was read
    sources: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.items, self.tainted, self.sources = [], False, []

    def unfinished(self) -> list[TodoItem]:
        return [i for i in self.items if i.status != "completed"]

    @property
    def done(self) -> bool:
        return bool(self.items) and not self.unfinished()

    def counts(self) -> tuple[int, int]:
        """(completed, total)"""
        return sum(i.status == "completed" for i in self.items), len(self.items)

    def text(self, only_open: bool = False) -> str:
        """The list as the model and the terminal see it: one numbered line per item."""
        rows = [f"{MARKS[i.status]} {n}. {i.content}" for n, i in enumerate(self.items, 1) if not (only_open and i.status == "completed")]
        return "\n".join(rows)

    def as_data(self) -> list[dict]:
        return [{"content": i.content, "status": i.status} for i in self.items]

    def quoted(self, only_open: bool = True) -> str:
        """The list for the harness to say back to the model: plain, or fenced when it was written after untrusted reading."""
        body = self.text(only_open)
        return fence(body, "todo list written after untrusted content was read") if self.tainted else body


def clean(text: str) -> str:
    """One line, no control characters (a model-written item is shown in a terminal), and not too long."""
    text = CONTROL.sub(" ", text).strip()
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS - 1].rstrip() + "…"


def validate(raw) -> tuple[list[TodoItem], list[str]]:
    """The model's `todos` argument -> (items, notes about what was adjusted). Raises TodoError, with advice, when it can't be used."""
    if not isinstance(raw, list):
        raise TodoError("todos must be a list of items, each like {\"content\": \"what to do\", \"status\": \"pending\"}")
    if len(raw) > MAX_ITEMS:
        raise TodoError(f"too many items ({len(raw)}; the limit is {MAX_ITEMS}): group small steps into one item")
    items, notes = [], []
    for n, entry in enumerate(raw, 1):
        if isinstance(entry, str):                       # ["step one", "step two"]: every item pending
            content, status = entry, "pending"
        elif isinstance(entry, dict):
            content = entry.get("content", entry.get("task", entry.get("text", entry.get("title", ""))))
            status = entry.get("status", "pending")
        else:
            raise TodoError(f"item {n} must be an object like {{\"content\": \"...\", \"status\": \"pending\"}}")
        if not isinstance(content, str) or not clean(content):
            raise TodoError(f"item {n} has no content: say what to do, in a few words")
        key = str(status).strip().lower()
        key = ALIASES.get(key, key)
        if key not in STATUSES:
            raise TodoError(f"item {n}: status '{status}' isn't one of {', '.join(STATUSES)}")
        items.append(TodoItem(clean(content), key))
    active = [i for i in items if i.status == "in_progress"]
    if len(active) > 1:                                  # work on one thing at a time: keep the first, say so
        for extra in active[1:]:
            extra.status = "pending"
        notes.append(f"{len(active)} items were in_progress; kept the first and set the others to pending (work on one at a time)")
    return items, notes


NUMBERED = re.compile(r"^\s{0,3}(\d{1,2})[.)]\s+(\S.*?)\s*$")
SEED_MIN = 3


def numbered_items(text: str) -> list[TodoItem]:
    """The numbered lines of a request ("1. fix it\\n2. test it\\n3. write it up"), as a todo list, or [] when there are fewer than three.
    This is the user's own list: the harness doesn't need the model to copy it before it can be kept."""
    found = [clean(m.group(2)) for line in text.splitlines() if (m := NUMBERED.match(line))]
    items = [TodoItem(c, "pending") for c in found if c][:MAX_ITEMS]
    if len(items) < SEED_MIN:
        return []
    items[0].status = "in_progress"
    return items


def from_messages(messages: list[Message]) -> list[TodoItem] | None:
    """The list as the conversation last said it: the newest `todo_write` call that was valid. None when there was none."""
    for m in reversed(messages):
        for call in reversed(m.tool_calls):
            if call.name == TOOL_NAME:
                try:
                    return validate(call.arguments.get("todos"))[0]
                except TodoError:
                    continue
    return None


def result_text(todos: TodoList, notes: list[str]) -> str:
    done, total = todos.counts()
    if not todos.items:
        return "Todo list cleared."
    head = f"Todo list updated ({done} of {total} done):"
    tail = ""
    if todos.done:
        tail = "All items are completed."
    elif not any(i.status == "in_progress" for i in todos.items):
        tail = "No item is in_progress: mark the one you are starting."
    else:
        tail = "Carry on with the item in progress; mark it completed as soon as it is done."
    return "\n".join([head, todos.text(), *(f"Note: {n}" for n in notes), tail])


NUDGE = ("[Note from the harness: your todo list still has unfinished items:\n{items}\n"
         "If they are done, mark them completed with todo_write. If they are no longer needed, remove them. Otherwise carry on with the next one.]")


def nudge_text(todos: TodoList) -> str | None:
    """What to say to a model that is about to finish with items still open, or None when nothing is."""
    if not todos.unfinished():
        return None
    return NUDGE.format(items=todos.quoted(only_open=True))


def make_todo_tools(state: TodoList, taint: Taint, on_change=None) -> list[Tool]:
    """`todo_write`: replace the list. `on_change(list)` is told after every successful write (for the interface)."""

    @tool(read_only=True, concurrency_safe=False)
    def todo_write(todos: list) -> str:
        """Keep a checklist for a job with several steps. Send the WHOLE list each time. Items: {"content": "...", "status": "pending" | "in_progress" | "completed"}.
        One item in_progress at a time; mark it completed when done. Not for questions or one-step jobs.

        Args:
            todos: the complete list.
        """
        items, notes = validate(todos)
        state.items = items
        if taint.active:                                  # written after untrusted reading: quoted back fenced, from now on
            state.tainted = True
            state.sources = list(taint.sources)
        elif not items:
            state.tainted, state.sources = False, []
        if on_change is not None:
            on_change(state)
        return result_text(state, notes)

    return [todo_write]
