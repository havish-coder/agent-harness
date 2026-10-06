"""Lessons 06-14: the agent loop. Model → tool calls → results → model ... until it answers.

This file is the heart of the harness. Everything else (tools, policy, context, UI) plugs in
around these few lines.
"""
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from harness.messages import Message, ToolCall, Usage
from harness.providers.base import Provider
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry

# on_event(kind, data) lets a UI show progress without the loop knowing anything about UIs.
# See docs/reference/events.md for the full list.
EventHandler = Callable[[str, Any], None]
# approve(call, tool) -> True to run a tool that can change things. Asked only for calls
# that aren't read-only.
Approver = Callable[[ToolCall, Tool], bool]

DENIED = ("The user denied this tool call, so it did not run. Do not try it again. "
          "Ask the user what they want to do instead.")
MAX_PARALLEL = 8   # concurrency-safe calls run on up to this many threads (Lesson 14)
NO_APPROVER = ("Error: this tool call can change things and needs the user's approval, "
               "but approval isn't possible in this session. Use read-only tools only.")


class Agent:
    def __init__(self, provider: Provider, tools: list[Tool] | ToolRegistry, system_prompt: str,
                 max_steps: int = 10, on_event: EventHandler | None = None,
                 approve: Approver | None = None):
        self.provider = provider
        self.tools = tools if isinstance(tools, ToolRegistry) else ToolRegistry(tools)
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.on_event = on_event or (lambda kind, data: None)
        self.approve = approve      # None = deny everything that isn't read-only (fail-closed)
        self.usage = Usage()
        # Why the last run() ended: "completed", "max_steps", "max_tokens", "cancelled", "error"
        self.stop_reason: str | None = None
        self.reset()

    def reset(self):
        """Forget the conversation (the model itself never remembered anything)."""
        self.messages = [Message.system(self.system_prompt)]

    def run(self, user_input: str) -> str:
        """Handle one user message. May call the model and tools many times."""
        turn_start = len(self.messages)
        self.messages.append(Message.user(user_input))
        schemas = self.tools.schemas()
        self.stop_reason = None

        try:
            for _ in range(self.max_steps):  # stop condition #2: never loop forever
                reply = self.provider.chat(self.messages, schemas)
                self.usage.input_tokens += reply.usage.input_tokens
                self.usage.output_tokens += reply.usage.output_tokens
                self.messages.append(reply.message)
                self.on_event("model_reply", reply)

                if not reply.message.tool_calls:  # stop condition #1: no tools wanted = final answer
                    if reply.stop_reason == "max_tokens":
                        self.stop_reason = "max_tokens"
                        return reply.message.content + "\n\n(reply cut off: output token limit reached)"
                    self.stop_reason = "completed"
                    return reply.message.content

                for batch in self.batches(reply.message.tool_calls):
                    for call in batch:
                        self.on_event("tool_call", call)
                    results = self.execute_batch(batch)
                    for call, result in zip(batch, results, strict=True):  # in the order the model asked
                        self.on_event("tool_result", (call, result))
                        self.messages.append(Message.tool_result(call, result))

            self.stop_reason = "max_steps"
            return f"(stopped: reached the limit of {self.max_steps} steps without a final answer)"
        except BaseException as e:
            # Error or Ctrl+C mid-turn: roll back this turn so the history stays consistent
            # (e.g. no assistant tool_calls left without their results).
            del self.messages[turn_start:]
            self.stop_reason = "cancelled" if isinstance(e, KeyboardInterrupt) else "error"
            raise

    def batches(self, calls: list[ToolCall]) -> list[list[ToolCall]]:
        """Group calls: consecutive concurrency-safe calls share a batch; any other call runs alone.

        Order is kept, so a write between two reads still happens after the first read and
        before the second (the model may depend on that).
        """
        groups: list[tuple[bool, list[ToolCall]]] = []   # (all safe?, calls)
        for call in calls:
            tool = self.tools.get(call.name)
            safe = tool is not None and tool.is_concurrency_safe(call.arguments)
            if safe and groups and groups[-1][0]:
                groups[-1][1].append(call)       # join the running batch of safe calls
            else:
                groups.append((safe, [call]))    # start a new batch (an unsafe call is always alone)
        return [batch for _, batch in groups]

    def execute_batch(self, batch: list[ToolCall]) -> list[str]:
        """Run one batch: a single call directly, several safe calls on threads."""
        if len(batch) == 1:
            return [self.execute(batch[0])]
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(batch))) as pool:
            return list(pool.map(self.execute, batch))

    def execute(self, call: ToolCall) -> str:
        """Run one tool call. Every failure becomes text for the model, never a crash."""
        tool, error = self.tools.resolve(call)
        if error:
            return error
        if tool.check:
            try:
                error = tool.check(**call.arguments)
            except Exception as e:
                error = f"Error: {type(e).__name__}: {e}"
            if error:
                return error
        if not tool.is_read_only(call.arguments):
            if self.approve is None:
                return NO_APPROVER
            if not self.approve(call, tool):
                self.on_event("tool_denied", call)
                return DENIED
        return self.tools.invoke(tool, call.arguments)
