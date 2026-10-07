"""Lesson 38: microcompaction. Give the window back by clearing old tool results.

Most of a long conversation is tool results: whole files, search hits, test output. A result is
needed while the model works on it and rarely afterwards, and for tools like `read_file` it can be
got again by calling the tool again. So when the window fills, the oldest of those results are
replaced by a short note saying what they were and how to get them back. No model call is needed
and nothing is summarised; the next lesson covers the case where clearing is not enough.

Rules this module keeps:
- only results of tools that declare themselves `clearable` (the answer can be got again);
- the most recent ones are always kept, because the model is working on them;
- oldest first, and only as many as needed (`need`);
- a result smaller than the note that would replace it is left alone;
- the note says what was cleared and how big it was, and **repeats none of its text**: a cleared
  result may have been untrusted content, and the note is not inside the fence (Lesson 31).
"""
from collections.abc import Callable, Container
from dataclasses import dataclass, field

from harness.context.tokens import estimate_tokens
from harness.messages import Message, ToolCall

STUB_START = "[cleared to save space:"
MIN_TOKENS = 150            # a result must cost at least this to be worth replacing (the note costs about 50)
TARGET_SHARE = 0.5          # clearing, once started, goes on until the conversation is this share of its limit
ARGUMENT_CHARS = 60         # each argument is shortened to this many characters in the note


@dataclass
class Cleared:
    """One result that was replaced."""
    call_id: str
    tool: str
    tokens: int             # what it cost before
    saved: int              # what clearing it gave back


@dataclass
class MicroResult:
    cleared: list[Cleared] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return sum(c.saved for c in self.cleared)

    def __bool__(self) -> bool:
        return bool(self.cleared)


def is_stub(message: Message) -> bool:
    return message.role == "tool" and message.content.startswith(STUB_START)


def describe_call(call: ToolCall | None, tool: str | None) -> str:
    """`read_file(path='big.txt')`, with long values shortened; just the name if the call isn't in the history."""
    if call is None:
        return tool or "tool"
    args = ", ".join(f"{k}={_short(v)}" for k, v in call.arguments.items())
    return f"{call.name}({args})"


def _short(value) -> str:
    text = repr(value)
    return text if len(text) <= ARGUMENT_CHARS else text[:ARGUMENT_CHARS - 1] + "…"


def make_stub(call: ToolCall | None, message: Message) -> str:
    """The note that replaces a result. Numbers and the call only: none of the result's own words."""
    lines = message.content.count("\n") + 1
    return (f"{STUB_START} {describe_call(call, message.tool_name)}, about {estimate_tokens(message.content):,} tokens, "
            f"{lines:,} lines. Call the tool again if you still need it.]")


def digested_after(messages: list[Message], is_action: Callable[[ToolCall], bool]) -> list[bool]:
    """For each message: has the model done something since it, that would have used what it said?

    The model has *used* a result when, later in the conversation, it wrote something (a reply with text) or made a call
    that changes things (`is_action`). A model that only went on reading has not: what it read exists nowhere else."""
    flags = [False] * len(messages)
    acted = False
    for i in range(len(messages) - 1, -1, -1):
        flags[i] = acted
        m = messages[i]
        if m.role == "assistant" and (m.content.strip() or any(is_action(c) for c in m.tool_calls)):
            acted = True
    return flags


def clear_old_results(messages: list[Message], clearable: Container[str], keep_recent: int = 2,
                      need: int | None = None, min_tokens: int = MIN_TOKENS,
                      is_action: Callable[[ToolCall], bool] | None = None) -> MicroResult:
    """Replace old results of `clearable` tools with notes, oldest first, in place in `messages`.

    keep_recent: the newest this many results of clearable tools that are big enough to be worth a note are never touched.
    need: stop once this many tokens are freed; None clears everything that may be cleared.
    is_action: when given, only results the model has used since (see `digested_after`) are cleared.
    """
    calls = {c.id: c for m in messages for c in m.tool_calls}
    positions = [i for i, m in enumerate(messages) if m.role == "tool" and m.tool_name in clearable]
    # "the newest results" are the ones worth clearing: a small result (or a note) is no use to protect, and counting it would
    # leave a big, older one unprotectable by the same rule (a one-line command result between two file reads)
    weighty = [i for i in positions if not is_stub(messages[i]) and estimate_tokens(messages[i].content) >= min_tokens]
    protected = set(weighty[-keep_recent:]) if keep_recent > 0 else set()
    used = digested_after(messages, is_action) if is_action is not None else None
    result = MicroResult()
    for i in positions:
        message = messages[i]
        if i in protected or is_stub(message) or (need is not None and result.saved >= need) or (used is not None and not used[i]):
            continue
        before = estimate_tokens(message.content)
        if before < min_tokens:
            continue
        stub = make_stub(calls.get(message.tool_call_id or ""), message)
        saved = before - estimate_tokens(stub)
        if saved <= 0:
            continue
        messages[i] = Message("tool", stub, tool_call_id=message.tool_call_id, tool_name=message.tool_name)
        result.cleared.append(Cleared(message.tool_call_id or "", message.tool_name or "tool", before, saved))
    return result
