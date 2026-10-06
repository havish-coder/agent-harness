"""Test helpers: scripted replies with fixed token counts, so loop tests never vary."""
from harness.messages import Message, Reply, ToolCall, Usage
from harness.providers.fake import ScriptedProvider

__all__ = ["ScriptedProvider", "call", "calls", "final"]


def calls(*tool_calls: ToolCall) -> Reply:
    return Reply(Message("assistant", tool_calls=list(tool_calls)), "tool_calls", Usage(10, 5))


def final(text: str) -> Reply:
    return Reply(Message("assistant", text), "end", Usage(10, 5))


def call(tool_name: str, id: str = "c1", **arguments) -> ToolCall:
    return ToolCall(id, tool_name, arguments)
