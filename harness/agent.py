"""Lesson 06: the agent loop. Model → tool calls → results → model ... until it answers.

This file is the heart of the harness. Everything else (tools, policy, context, UI) plugs in
around these few lines.
"""
from collections.abc import Callable
from typing import Any

from harness.messages import Message, ToolCall, Usage
from harness.providers.base import Provider
from harness.tools.base import Tool

# on_event(kind, data) lets a UI show progress without the loop knowing anything about UIs.
#   "model_reply" → Reply    "tool_call" → ToolCall    "tool_result" → (ToolCall, str)
EventHandler = Callable[[str, Any], None]


class Agent:
    def __init__(self, provider: Provider, tools: list[Tool], system_prompt: str,
                 max_steps: int = 10, on_event: EventHandler | None = None):
        self.provider = provider
        self.tools = {t.name: t for t in tools}
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.on_event = on_event or (lambda kind, data: None)
        self.usage = Usage()
        self.reset()

    def reset(self):
        """Forget the conversation (the model itself never remembered anything)."""
        self.messages = [Message.system(self.system_prompt)]

    def run(self, user_input: str) -> str:
        """Handle one user message. May call the model and tools many times."""
        turn_start = len(self.messages)
        self.messages.append(Message.user(user_input))
        schemas = [t.schema() for t in self.tools.values()]

        try:
            for _ in range(self.max_steps):  # stop condition #2: never loop forever
                reply = self.provider.chat(self.messages, schemas)
                self.usage.input_tokens += reply.usage.input_tokens
                self.usage.output_tokens += reply.usage.output_tokens
                self.messages.append(reply.message)
                self.on_event("model_reply", reply)

                if not reply.message.tool_calls:  # stop condition #1: no tools wanted = final answer
                    if reply.stop_reason == "max_tokens":
                        return reply.message.content + "\n\n(reply cut off: output token limit reached)"
                    return reply.message.content

                for call in reply.message.tool_calls:
                    self.on_event("tool_call", call)
                    result = self.execute(call)
                    self.on_event("tool_result", (call, result))
                    self.messages.append(Message.tool_result(call, result))

            return f"(stopped: reached the limit of {self.max_steps} steps without a final answer)"
        except BaseException:
            # Error or Ctrl+C mid-turn: roll back this turn so the history stays consistent
            # (e.g. no assistant tool_calls left without their results).
            del self.messages[turn_start:]
            raise

    def execute(self, call: ToolCall) -> str:
        """Run one tool. Errors become text for the model, never crashes."""
        tool = self.tools.get(call.name)
        if tool is None:
            return f"Error: unknown tool '{call.name}'. Available tools: {', '.join(self.tools)}"
        try:
            return str(tool.fn(**call.arguments))
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
