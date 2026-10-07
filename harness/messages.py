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
    # user messages the harness started a turn with: an id the file history and /rewind use to find this request again (Lesson 43)
    checkpoint: str | None = field(default=None, compare=False)

    @classmethod
    def system(cls, text: str) -> "Message":
        return cls("system", text)

    @classmethod
    def user(cls, text: str, checkpoint: str | None = None) -> "Message":
        return cls("user", text, checkpoint=checkpoint)

    @classmethod
    def tool_result(cls, call: ToolCall, content: str) -> "Message":
        return cls("tool", content, tool_call_id=call.id, tool_name=call.name)


@dataclass
class Usage:
    input_tokens: int = 0          # everything the model read, cached or not
    output_tokens: int = 0
    cache_read_tokens: int = 0     # part of input_tokens served from a prompt cache (Lesson 21)
    cache_write_tokens: int = 0    # part of input_tokens stored into a prompt cache

    def __iadd__(self, other: "Usage") -> "Usage":
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        return self

    def __sub__(self, other: "Usage") -> "Usage":
        return Usage(self.input_tokens - other.input_tokens, self.output_tokens - other.output_tokens,
                     self.cache_read_tokens - other.cache_read_tokens,
                     self.cache_write_tokens - other.cache_write_tokens)

    def copy(self) -> "Usage":
        return Usage(self.input_tokens, self.output_tokens, self.cache_read_tokens, self.cache_write_tokens)


@dataclass
class Reply:
    """Everything one model call returns, in provider-neutral form."""

    message: Message         # always role="assistant"
    stop_reason: StopReason  # "end" = final answer, "tool_calls" = wants tools, "max_tokens" = cut off
    usage: Usage
    model: str | None = None  # which model actually answered (a fallback may differ), for costs


# --- Lesson 15: plain-dict form, for recordings (and sessions, Lesson 40) ---

def message_to_dict(m: Message) -> dict:
    d: dict = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls]
    if m.tool_call_id is not None:
        d["tool_call_id"] = m.tool_call_id
        d["tool_name"] = m.tool_name
    if m.checkpoint is not None:
        d["checkpoint"] = m.checkpoint
    return d


def message_from_dict(d: dict) -> Message:
    return Message(d["role"], d.get("content", ""),
                   tool_calls=[ToolCall(c["id"], c["name"], c["arguments"]) for c in d.get("tool_calls", [])],
                   tool_call_id=d.get("tool_call_id"), tool_name=d.get("tool_name"), checkpoint=d.get("checkpoint"))


def reply_to_dict(r: Reply) -> dict:
    usage = {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens}
    if r.usage.cache_read_tokens or r.usage.cache_write_tokens:
        usage |= {"cache_read_tokens": r.usage.cache_read_tokens, "cache_write_tokens": r.usage.cache_write_tokens}
    return {"message": message_to_dict(r.message), "stop_reason": r.stop_reason, "usage": usage}


def reply_from_dict(d: dict) -> Reply:
    return Reply(message_from_dict(d["message"]), d["stop_reason"], Usage(**d["usage"]))
