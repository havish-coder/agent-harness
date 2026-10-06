"""Test helpers: a scripted fake model, so loop tests need no GPU and never vary."""
from harness.messages import Message, Reply, ToolCall, Usage


class ScriptedProvider:
    """Returns pre-written replies in order and records every request it received."""
    model = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []          # (messages, tools) per call, for assertions

    def chat(self, messages, tools):
        self.requests.append((list(messages), tools))
        return self.replies.pop(0)


def calls(*tool_calls: ToolCall) -> Reply:
    return Reply(Message("assistant", tool_calls=list(tool_calls)), "tool_calls", Usage(10, 5))


def final(text: str) -> Reply:
    return Reply(Message("assistant", text), "end", Usage(10, 5))


def call(name: str, id: str = "c1", **arguments) -> ToolCall:
    return ToolCall(id, name, arguments)
