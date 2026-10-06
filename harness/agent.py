"""Lessons 06-16: the agent loop. Model → tool calls → results → model ... until it answers.

This file is the heart of the harness. Everything else (tools, policy, context, UI) plugs in
around these few lines.
"""
import inspect
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from harness.messages import Message, Reply, ToolCall, Usage
from harness.providers.base import Provider, ProviderError, StreamingProvider, TextDelta, ThinkingDelta
from harness.security.permissions import AskForChanges, Decision, Permissions
from harness.security.taint import fence
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry

# on_event(kind, data) lets a UI show progress without the loop knowing anything about UIs.
# See docs/reference/events.md for the full list.
EventHandler = Callable[[str, Any], None]
# approve(call, tool[, decision]) -> True to run the call, False to refuse it, or "always" to run
# it and add `decision.remember` as a session rule. Asked only when the permissions say "ask"
# (Lesson 29). An approver that accepts a `decision` argument gets the reason it is being asked.
Approver = Callable[..., bool | str]

DENIED = ("The user denied this tool call, so it did not run. Do not try it again. "
          "Ask the user what they want to do instead.")
MAX_PARALLEL = 8   # concurrency-safe calls run on up to this many threads (Lesson 14)
NO_APPROVER = ("Error: this tool call can change things and needs the user's approval, "
               "but approval isn't possible in this session. Use read-only tools only.")


class Agent:
    def __init__(self, provider: Provider, tools: list[Tool] | ToolRegistry, system_prompt: str,
                 max_steps: int = 10, on_event: EventHandler | None = None,
                 approve: Approver | None = None, stream: bool = True,
                 permissions: Permissions | None = None, fence_untrusted: bool = False):
        self.provider = provider
        self.tools = tools if isinstance(tools, ToolRegistry) else ToolRegistry(tools)
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.on_event = on_event or (lambda kind, data: None)
        self.approve = approve      # None = deny everything that isn't read-only (fail-closed)
        self.permissions = permissions or AskForChanges()   # decides allow / ask / deny (Lesson 29)
        self._approve_takes_decision = approve is not None and _accepts(approve, "decision")
        self.stream = stream        # use the provider's stream() when it has one (Lesson 16)
        self.fence_untrusted = fence_untrusted   # wrap outside content in <untrusted> tags (Lesson 31)
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
        seen: dict[str, tuple[str, int]] = {}   # call → (result, times seen), for note_repeats

        try:
            for _ in range(self.max_steps):  # stop condition #2: never loop forever
                reply = self.call_model(schemas)
                self.usage += reply.usage
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
                    outcomes = self.execute_outcomes(batch)
                    for call, (result, ran) in zip(batch, outcomes, strict=True):  # in the order the model asked
                        result = self.note_repeats(seen, call, result)
                        self.on_event("tool_result", (call, result))
                        self.messages.append(Message.tool_result(call, self.mark_untrusted(call, result, ran)))

            self.stop_reason = "max_steps"
            return f"(stopped: reached the limit of {self.max_steps} steps without a final answer)"
        except BaseException as e:
            # Error or Ctrl+C mid-turn: roll back this turn so the history stays consistent
            # (e.g. no assistant tool_calls left without their results).
            del self.messages[turn_start:]
            self.stop_reason = "cancelled" if isinstance(e, KeyboardInterrupt) else "error"
            raise

    def call_model(self, schemas: list[dict]) -> Reply:
        """One model call. Streams text out as events when the provider can (Lesson 16)."""
        self.on_event("model_call", len(self.messages))
        if not (self.stream and isinstance(self.provider, StreamingProvider)):
            return self.provider.chat(self.messages, schemas)
        reply = None
        for item in self.provider.stream(self.messages, schemas):
            if isinstance(item, TextDelta):
                self.on_event("text_delta", item.text)
            elif isinstance(item, ThinkingDelta):
                self.on_event("thinking_delta", item.text)
            else:
                reply = item
        if reply is None:
            raise ProviderError("the model's stream ended without a complete reply", retryable=True)
        return reply

    @staticmethod
    def note_repeats(seen: dict, call: ToolCall, result: str) -> str:
        """Small models can loop on a failing call. Tell them when a call repeats exactly (Lesson 15)."""
        key = call.name + json.dumps(call.arguments, sort_keys=True, default=str)
        previous, times = seen.get(key, (None, 0))
        if previous == result:
            seen[key] = (result, times + 1)
            return (f"{result}\n\n[note: you have made exactly this call {times + 1} times in this task "
                    "and got the same result each time. Repeating it will not help: change the "
                    "arguments, check paths and folders, or try a different approach.]")
        seen[key] = (result, 1)
        return result

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

    def mark_untrusted(self, call: ToolCall, result: str, ran: bool) -> str:
        """What the model reads for this result (Lesson 31). Text that carries content someone else
        may have written is remembered as a taint source and, when fencing is on, wrapped in
        <untrusted> tags. Refusals and errors are the harness's own words and stay as they are."""
        tool = self.tools.get(call.name)
        if not (ran and tool and tool.content_kind) or result.startswith("Error"):
            return result
        source = f"{call.name} {_subject_text(call, tool)}".strip()
        taint = getattr(self.permissions, "taint", None)
        if taint is not None:
            taint.add(tool.content_kind, source)
        return fence(result, source) if self.fence_untrusted else result

    def execute_batch(self, batch: list[ToolCall]) -> list[str]:
        """Run one batch; the results are texts, in the order of `batch`."""
        return [text for text, _ in self.execute_outcomes(batch)]

    def execute_outcomes(self, batch: list[ToolCall]) -> list[tuple[str, bool]]:
        """(text, whether the tool actually ran) for each call. Every call is checked and decided on
        this thread first, so events and questions to the user never come from a worker thread; then
        the allowed calls run: one directly, several safe ones on threads."""
        prepared = [self.prepare(call) for call in batch]
        results = [text for _, text in prepared]
        runnable = [(i, tool, call) for i, ((tool, _), call) in enumerate(zip(prepared, batch, strict=True)) if tool]
        if len(runnable) == 1:
            i, tool, call = runnable[0]
            results[i] = self.tools.invoke(tool, call.arguments)
        elif runnable:
            with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(runnable))) as pool:
                done = pool.map(lambda r: self.tools.invoke(r[1], r[2].arguments), runnable)
                for (i, _, _), text in zip(runnable, done, strict=True):
                    results[i] = text
        ran = {i for i, _, _ in runnable}
        return [(text, i in ran) for i, text in enumerate(results)]

    def execute(self, call: ToolCall) -> str:
        """Run one tool call. Every failure becomes text for the model, never a crash."""
        return self.execute_batch([call])[0]

    def prepare(self, call: ToolCall) -> tuple[Tool | None, str | None]:
        """(tool, None) when the call may run, or (None, text for the model) when it may not:
        unknown tool, bad arguments, the tool's own check, the permissions, the user's answer."""
        tool, error = self.tools.resolve(call)
        if error:
            return None, error
        if tool.check:
            try:
                error = tool.check(**call.arguments)
            except Exception as e:
                error = f"Error: {type(e).__name__}: {e}"
            if error:
                return None, error
        decision = self.permissions.decide(call, tool)
        self.on_event("permission", (call, decision))
        if decision.action == "deny":
            self.on_event("tool_refused", (call, decision.reason))
            return None, (f"Error: not allowed: {decision.reason}. Don't try this again another way; "
                          "if it's needed, ask the user.")
        if decision.action == "ask":
            answer = self.ask_user(call, tool, decision)
            if answer is None:
                return None, NO_APPROVER
            if not answer:
                self.on_event("tool_denied", call)
                return None, DENIED
            if answer == "always" and decision.remember:
                self.permissions.remember(decision.remember)
        return tool, None

    def ask_user(self, call: ToolCall, tool: Tool, decision: Decision) -> bool | str | None:
        """The approver's answer, or None when there is no one to ask."""
        if self.approve is None:
            return None
        if self._approve_takes_decision:
            return self.approve(call, tool, decision=decision)
        return self.approve(call, tool)


def _subject_text(call: ToolCall, tool: Tool) -> str:
    """A short label for what a call touched: its path, command or url."""
    value = call.arguments.get(tool.subject) if tool.subject else None
    text = " ".join(str(value).split()) if value is not None else ""
    return text if len(text) <= 60 else text[:57] + "..."


def _accepts(fn: Callable, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
