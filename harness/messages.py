"""Lesson 04: the harness's own message format.

Every provider (Ollama, OpenAI, Anthropic...) has its own JSON dialect. The rest of the
harness never touches those dialects: it only uses these types, and each provider
adapter translates to and from them (Lesson 05).
"""
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["system", "user", "assistant", "tool"]
StopReason = Literal["end", "tool_calls", "max_tokens"]


@dataclass
class ToolCall:
    """The model asking the harness to run a tool. The model never runs anything itself."""

    id: str          # links this request to its result; some APIs require it
    name: str
    arguments: dict


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # assistant messages only
    tool_call_id: str | None = None                            # tool messages only: which call this answers
    tool_name: str | None = None                               # tool messages only

    @classmethod
    def system(cls, text: str) -> "Message":
        return cls("system", text)

    @classmethod
    def user(cls, text: str) -> "Message":
        return cls("user", text)

    @classmethod
    def tool_result(cls, call: ToolCall, content: str) -> "Message":
        return cls("tool", content, tool_call_id=call.id, tool_name=call.name)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Reply:
    """Everything one model call returns, in provider-neutral form."""

    message: Message         # always role="assistant"
    stop_reason: StopReason  # "end" = final answer, "tool_calls" = wants tools, "max_tokens" = cut off
    usage: Usage
