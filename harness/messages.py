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


# --- Lesson 15: plain-dict form, for recordings (and sessions, Lesson 40) ---

def message_to_dict(m: Message) -> dict:
    d: dict = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls]
    if m.tool_call_id is not None:
        d["tool_call_id"] = m.tool_call_id
        d["tool_name"] = m.tool_name
    return d


def message_from_dict(d: dict) -> Message:
    return Message(d["role"], d.get("content", ""),
                   tool_calls=[ToolCall(c["id"], c["name"], c["arguments"]) for c in d.get("tool_calls", [])],
                   tool_call_id=d.get("tool_call_id"), tool_name=d.get("tool_name"))


def reply_to_dict(r: Reply) -> dict:
    return {"message": message_to_dict(r.message), "stop_reason": r.stop_reason,
            "usage": {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens}}


def reply_from_dict(d: dict) -> Reply:
    return Reply(message_from_dict(d["message"]), d["stop_reason"], Usage(**d["usage"]))
