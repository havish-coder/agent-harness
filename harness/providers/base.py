"""Lessons 05 and 16: the provider interface. Every LLM backend the harness can use implements this.

Tool schemas passed to a provider use a neutral shape:
    {"name": "read_file", "description": "...", "parameters": {<JSON Schema>}}
Each provider wraps them in its own vendor format.

Streaming (Lesson 16) is optional: a provider that has `stream()` yields text as it is
generated, then the complete Reply as its last item.
"""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from harness.messages import Message, Reply


class ProviderError(Exception):
    """The model backend failed: unreachable, unknown model, bad request, timeout..."""

    def __init__(self, message: str, status: int | None = None, retryable: bool = False,
                 retry_after: float | None = None):
        super().__init__(message)
        self.status = status            # HTTP status, if there was one
        self.retryable = retryable      # worth trying again? (Lesson 19)
        self.retry_after = retry_after  # seconds the server asked us to wait, if it said


@dataclass
class TextDelta:
    """A piece of the answer, as soon as the model produced it."""
    text: str


@dataclass
class ThinkingDelta:
    """A piece of the model's reasoning, for models that think before answering."""
    text: str


StreamItem = TextDelta | ThinkingDelta | Reply


class Provider(Protocol):
    model: str

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply:
        """Send the whole conversation plus tool schemas; return the model's next message."""
        ...


@runtime_checkable
class StreamingProvider(Provider, Protocol):
    def stream(self, messages: list[Message], tools: list[dict]) -> Iterator[StreamItem]:
        """Like chat(), but yield TextDelta/ThinkingDelta items while generating, then the Reply."""
        ...
