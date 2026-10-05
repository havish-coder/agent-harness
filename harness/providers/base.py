"""Lesson 05: the provider interface. Every LLM backend the harness can use implements this.

Tool schemas passed to a provider use a neutral shape:
    {"name": "read_file", "description": "...", "parameters": {<JSON Schema>}}
Each provider wraps them in its own vendor format.
"""
from typing import Protocol

from harness.messages import Message, Reply


class ProviderError(Exception):
    """The model backend failed: unreachable, unknown model, bad request, timeout..."""


class Provider(Protocol):
    model: str

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply:
        """Send the whole conversation plus tool schemas; return the model's next message."""
        ...
