"""Lesson 34: limits on a whole session (threat T13: runaway use).

`max_steps` already stops a single request that never ends. These limits stop a *session* that
runs too long, makes too many calls or costs too much, whether it is looping, being steered by
injected text, or simply working for hours. They are checked before each model call and before
each tool call, by plain code; the model never sees them (until one is hit, and then it is told).
"""
import time
from dataclasses import dataclass, field


@dataclass
class Limits:
    max_tool_calls: int | None = 500        # tool calls in this session
    max_cost: float | None = 5.0            # US dollars, for models with a known price
    max_tokens: int | None = None           # input + output tokens, summed over every model call
    max_minutes: float | None = None        # wall-clock time since the session started
    started: float = field(default_factory=time.monotonic)
    tool_calls: int = 0
    tokens: int = 0                         # counted by the session: input + output of every model call

    def exceeded(self, tokens: int | None = None, cost: float | None = None) -> str | None:
        """Why the session must stop, in words for the user, or None. `cost` is the money spent in
        this chat, which the session knows (it holds the prices); None for a model with no price."""
        tokens = self.tokens if tokens is None else tokens
        if self.max_tool_calls is not None and self.tool_calls >= self.max_tool_calls:
            return f"{self.tool_calls} tool calls (limit {self.max_tool_calls})"
        if self.max_cost is not None and cost is not None and cost >= self.max_cost:
            return f"${cost:.2f} spent (limit ${self.max_cost:.2f})"
        if self.max_tokens is not None and tokens >= self.max_tokens:
            return f"{tokens:,} tokens used (limit {self.max_tokens:,})"
        if self.max_minutes is not None and (time.monotonic() - self.started) / 60 >= self.max_minutes:
            return f"{(time.monotonic() - self.started) / 60:.0f} minutes (limit {self.max_minutes:g})"
        return None

    def reset(self) -> None:
        """A new conversation starts counting again (the limits are per chat)."""
        self.started, self.tool_calls, self.tokens = time.monotonic(), 0, 0
