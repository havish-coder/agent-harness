"""Lessons 06-16: the agent loop. Model → tool calls → results → model ... until it answers.

This file is the heart of the harness. Everything else (tools, policy, context, UI) plugs in
around these few lines.
"""
import inspect
import json
import secrets
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from harness.context.compact import (
    FALLBACK_BUDGET,
    KEEP_SHARE,
    MAX_FAILURES,
    MIN_GAP,
    MIN_HEAD_TOKENS,
    Compaction,
    current_request,
    rebuild,
    split,
    summarise,
)
from harness.context.micro import TARGET_SHARE, MicroResult, clear_old_results
from harness.context.tokens import ContextBudget, ContextStatus, message_tokens
from harness.hooks import Hooks
from harness.messages import Message, Reply, ToolCall, Usage
from harness.providers.base import Provider, ProviderError, StreamingProvider, TextDelta, ThinkingDelta
from harness.security.permissions import CHANGES, AskForChanges, Decision, Permissions
from harness.security.redact import redact
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
MAX_NUDGES = 2     # a model that finishes with work open is sent back at most this many times per request (Lesson 44)
MAX_PARALLEL = 8   # concurrency-safe calls run on up to this many threads (Lesson 14)
HOOK_REFUSAL = "a hook refused it:"
NO_APPROVER = ("Error: this tool call can change things and needs the user's approval, "
               "but approval isn't possible in this session. Use read-only tools only.")


class Agent:
    def __init__(self, provider: Provider, tools: list[Tool] | ToolRegistry, system_prompt: str,
                 max_steps: int = 10, on_event: EventHandler | None = None,
                 approve: Approver | None = None, stream: bool = True,
                 permissions: Permissions | None = None, fence_untrusted: bool = False,
                 hooks: Hooks | None = None, redact_results: bool = False,
                 limit_check: Callable[[], str | None] | None = None, context: ContextBudget | None = None,
                 microcompact: bool = False, keep_recent: int = 2, auto_compact: bool = False,
                 call_notes: Callable[[ToolCall], str] | None = None,
                 finish_check: Callable[[], str | None] | None = None, carry: Callable[[], str] | None = None,
                 notices: Callable[[], list[str]] | None = None,
                 on_request: Callable[[str], str | None] | None = None):
        self.provider = provider
        self.tools = tools if isinstance(tools, ToolRegistry) else ToolRegistry(tools)
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.on_event = on_event or (lambda kind, data: None)
        self.approve = approve      # None = deny everything that isn't read-only (fail-closed)
        self.permissions = permissions or AskForChanges()   # decides allow / ask / deny (Lesson 29)
        self._approve_takes_decision = approve is not None and _accepts(approve, "decision")
        self.stream = stream        # use the provider's stream() when it has one (Lesson 16)
        self.redact_results = redact_results     # hide secrets in tool results (Lesson 34)
        self.limit_check = limit_check           # returns why the session must stop, or None (Lesson 34)
        self.context = context      # measures the conversation against the model's window (Lesson 36)
        self.microcompact = microcompact   # clear old results when the window fills (Lesson 38) ...
        self.keep_recent = max(1, keep_recent)   # ... but not the newest this many (at least the newest one)
        self.auto_compact = auto_compact   # summarise the older conversation when clearing isn't enough (Lesson 39)
        self.call_notes = call_notes       # text to show beside a result: a folder's own notes (Lesson 41)
        self.finish_check = finish_check   # says what is still open when the model tries to finish; the agent asks it to carry on (Lesson 44)
        self.on_request = on_request       # looks at a new request and may add a note to it (the todo list from numbered items, Lesson 44)
        self.notices = notices             # things that happened while the model was busy (a background task ended), said between steps (Lesson 48)
        self.carry = carry                 # state to repeat in a summary, so compaction doesn't lose it: the todo list (Lesson 44)
        self.hooks = hooks          # the user's scripts at fixed points (Lesson 33)
        self.fence_untrusted = fence_untrusted   # wrap outside content in <untrusted> tags (Lesson 31)
        self.usage = Usage()
        # Why the last run() ended: "completed", "max_steps", "max_tokens", "cancelled", "error"
        self.stop_reason: str | None = None
        self.reset()

    def reset(self):
        """Forget the conversation (the model itself never remembered anything)."""
        self.messages = [Message.system(self.system_prompt)]
        self.cleared_results = 0     # results replaced by notes in this conversation, and the tokens that gave back
        self.cleared_tokens = 0
        self.compactions = 0         # times the older conversation was replaced by a summary (Lesson 39)
        self.archive: list[Message] = []     # the messages those summaries replaced, oldest first
        self.calls_since_compact = MIN_GAP
        self.compact_failures = 0    # failures in a row; automatic compaction stops trying at MAX_FAILURES
        self.compact_error: str | None = None     # why the last compact() did nothing, when the model was the problem
        self.turn_start = 1          # where this turn's messages begin, for rolling it back after an error
        self.pending_notes: list[str] = []      # told to the model with the next request, then forgotten
        self.nudges = 0              # times this request was sent back to work because finish_check found something open (at most MAX_NUDGES)
        self.denied = False          # the user said no to a call in this request: nobody pushes the model to carry on after that

    def run(self, user_input: str) -> str:
        """Handle one user message. May call the model and tools many times."""
        if self.hooks:
            blocked, user_input = self.prompt_hooks(user_input)
            if blocked:
                self.stop_reason = "blocked"
                return blocked
        if self.pending_notes:                 # something the user did between turns that the model can't know (Lesson 43)
            notes = " ".join(self.pending_notes)
            user_input = f"[Note from the harness: {notes}]\n\n{user_input}"
            self.pending_notes.clear()
        extra = self.on_request(user_input) if self.on_request else None
        if extra:
            user_input = f"{user_input}\n\n[Note from the harness: {extra}]"
        self.turn_start = len(self.messages)
        self.nudges, self.denied = 0, False
        self.add(Message.user(user_input, checkpoint=secrets.token_hex(4)))
        self.stop_reason = None
        seen: dict[str, tuple[str, int]] = {}   # call → (result, times seen), for note_repeats

        try:
            for _ in range(self.max_steps):  # stop condition #2: never loop forever
                # built every step: a tool tool_search loaded, or one switched on (plan mode), is callable on the very next call (Lesson 50)
                schemas = self.tools.schemas()
                for note in (self.notices() if self.notices else []):
                    self.add(Message.user(f"[Note from the harness: {note}]"))
                    self.on_event("notice", note)
                why = self.limit_check() if self.limit_check else None
                if why:                       # stop condition #3: a session-wide limit (Lesson 34)
                    self.stop_reason = "limit"
                    self.on_event("limit", why)
                    return (f"(stopped: {why}. /limits shows the limits; raise one in your settings, "
                            "or /reset to start a new chat)")
                status = self.context.check(self.messages, schemas) if self.context else None
                if status and self.microcompact and status.level != "ok":
                    status = self.free_space(status, schemas)      # clear results the model has used (Lesson 38)
                # a summary answers "this doesn't fit", not "this is getting full": in a small window one big result is already 90%
                if (status and self.auto_compact and status.level == "full"
                        and self.calls_since_compact >= MIN_GAP and self.compact_failures < MAX_FAILURES and self.compact()):
                    status = self.context.check(self.messages, schemas)      # summarised: measure again (Lesson 39)
                if status and self.microcompact and status.level == "full":
                    status = self.free_space(status, schemas, last_resort=True)   # nothing else worked: clear unused results too
                if status:
                    self.on_event("context", status)
                    if status.level == "full":      # stop condition #4: never send what won't fit (Lesson 36)
                        self.stop_reason = "context_full"
                        return (f"(stopped: the conversation is about {status.estimated:,} tokens and the model's window "
                                f"leaves room for {status.limit:,}. /context shows where they go; /reset starts a new chat)")
                reply = self.call_model(schemas)
                self.calls_since_compact += 1
                if status:
                    self.context.observe(status, reply.usage.input_tokens)
                self.usage += reply.usage
                self.add(reply.message)
                self.on_event("model_reply", reply)

                if not reply.message.tool_calls:  # stop condition #1: no tools wanted = final answer
                    if reply.stop_reason == "max_tokens":
                        self.stop_reason = "max_tokens"
                        return reply.message.content + "\n\n(reply cut off: output token limit reached)"
                    note = self.open_work()
                    if note:                      # it wants to finish with items still open: say so, once or twice (Lesson 44)
                        self.nudges += 1
                        self.add(Message.user(note))
                        self.on_event("nudge", note)
                        continue
                    self.stop_reason = "completed"
                    return reply.message.content

                for batch in self.batches(reply.message.tool_calls):
                    for call in batch:
                        self.on_event("tool_call", call)
                    outcomes = self.execute_outcomes(batch)
                    for call, (result, ran) in zip(batch, outcomes, strict=True):  # in the order the model asked
                        result = self.hide_secrets(call, result)
                        result = self.note_repeats(seen, call, result)
                        from_hooks = self.post_hooks(call, result) if ran else ""     # the user's own words: not fenced
                        self.on_event("tool_result", (call, result + from_hooks))
                        note = self.call_notes(call) if self.call_notes and ran and not result.startswith("Error") else ""
                        self.add(Message.tool_result(call, self.mark_untrusted(call, result, ran) + from_hooks + note))

            self.stop_reason = "max_steps"
            return f"(stopped: reached the limit of {self.max_steps} steps without a final answer)"
        except BaseException as e:
            # Error or Ctrl+C mid-turn: roll back this turn so the history stays consistent
            # (e.g. no assistant tool_calls left without their results).
            del self.messages[self.turn_start:]
            self.on_event("rolled_back", len(self.messages) - 1)    # a saved chat undoes the same messages (Lesson 40)
            self.stop_reason = "cancelled" if isinstance(e, KeyboardInterrupt) else "error"
            raise

    def add(self, message: Message) -> None:
        """Add to the conversation, and tell whoever is saving it (Lesson 40)."""
        self.messages.append(message)
        self.on_event("message", message)

    def open_work(self) -> str | None:
        """What to tell a model that is about to finish, or None: nothing is open, it was told twice already, or the user refused something."""
        if self.finish_check is None or self.denied or self.nudges >= MAX_NUDGES:
            return None
        return self.finish_check()

    def acts(self, call: ToolCall) -> bool:
        """Does this call change something? A model that has made one has used what it read before (Lesson 39)."""
        tool = self.tools.get(call.name)
        return tool is not None and not tool.is_read_only(call.arguments)

    def free_space(self, status: ContextStatus, schemas: list[dict], last_resort: bool = False) -> ContextStatus:
        """The window is filling: replace old results of clearable tools with notes, oldest first, down to half
        the limit (so this doesn't run again on the very next call). If the conversation still doesn't fit, go on
        keeping only the newest result: in a small window "keep the last two" can be the whole window.

        Only results the model has *used* are cleared (it wrote something, or made a call that changes things, after
        reading them): what a model has only read, and gone on reading, exists nowhere else, and a summary can keep it.
        `last_resort` clears the unused ones too, when nothing else made room. Returns the status afterwards."""
        total = MicroResult()
        for keep in sorted({self.keep_recent, 1}, reverse=True):
            total.cleared += clear_old_results(self.messages, self.tools.clearable_names(), keep,
                                               need=self.context.to_free(status, TARGET_SHARE),
                                               is_action=None if last_resort else self.acts).cleared
            status = self.context.check(self.messages, schemas)
            if status.level != "full":
                break
        if total:
            self.cleared_results += len(total.cleared)
            self.cleared_tokens += total.saved
            self.on_event("microcompact", total)
        return status

    def compact(self, focus: str | None = None) -> Compaction | None:
        """Replace all but the newest messages with a model-written summary (Lesson 39). Returns what was done, or None
        when there was nothing worth summarising or the model couldn't write a summary: the conversation is then unchanged."""
        self.compact_error = None
        limit = self.context.limit if self.context else FALLBACK_BUDGET
        head, tail = split(self.messages, int(limit * KEEP_SHARE))
        if sum(message_tokens(m) for m in head) < MIN_HEAD_TOKENS:
            return None
        self.on_event("compacting", len(head))
        try:
            summary, reply = summarise(self.provider, head, limit, focus)
        except ProviderError as e:
            self.compact_failures += 1
            self.compact_error = str(e)
            self.on_event("compact_failed", self.compact_error)
            return None
        self.usage += reply.usage
        self.on_event("model_reply", reply)          # it was a model call: costs and limits count it
        if not summary:
            self.compact_failures += 1
            self.compact_error = "the model wrote an empty summary"
            self.on_event("compact_failed", self.compact_error)
            return None
        self.compact_failures = 0
        taint = getattr(self.permissions, "taint", None)
        untrusted = bool(self.fence_untrusted and taint is not None and taint.active)
        before = sum(message_tokens(m) for m in self.messages)
        cut = len(self.messages) - len(tail)
        rebuilt = rebuild(self.messages[0], summary, current_request(head, tail), tail, untrusted, self.carry() if self.carry else "")
        # the kept messages now start at index 2 (after the system prompt and the summary); a turn that began in the
        # summarised part is rolled back to just after the summary
        self.turn_start = 2 + self.turn_start - cut if self.turn_start >= cut else 2
        self.messages[:] = rebuilt
        self.archive.extend(head)
        self.compactions += 1
        self.calls_since_compact = 0
        done = Compaction(summary, len(head), before, sum(message_tokens(m) for m in rebuilt), head, untrusted)
        self.on_event("compact", done)
        return done

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

    def hide_secrets(self, call: ToolCall, result: str) -> str:
        """Replace secrets in a tool result before anyone, the model included, reads it (Lesson 34)."""
        if not self.redact_results:
            return result
        found = redact(result)
        if found.count:
            self.on_event("redacted", (call, found.found))
        return found.text

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
        if self.hooks and decision.action != "deny":
            decision = self.apply_hooks(call, tool, decision)
        self.on_event("permission", (call, decision))
        if decision.action == "deny":
            self.on_event("tool_refused", (call, decision.reason))
            if decision.reason.startswith(HOOK_REFUSAL):    # the user's own script explained itself: follow it
                return None, (f"Error: {decision.reason}. Do what that says; if it offers no alternative, "
                              "don't try another way: tell the user.")
            return None, (f"Error: not allowed: {decision.reason}. Don't try this again another way; "
                          "if it's needed, ask the user.")
        if decision.action == "ask":
            answer = self.ask_user(call, tool, decision)
            if answer is None:
                return None, NO_APPROVER
            if not answer:
                self.denied = True
                self.on_event("tool_denied", call)
                return None, DENIED
            self.on_event("tool_approved", (call, answer))
            if answer == "always" and decision.remember:
                self.permissions.remember(decision.remember)
        return tool, None

    # --- hooks (Lesson 33): they may tighten a decision, and loosen only a routine question ---------
    def apply_hooks(self, call: ToolCall, tool: Tool, decision: Decision) -> Decision:
        result = self.hooks.pre_tool(call, tool)
        if not (result.decision or result.failed or result.context):
            return decision
        self.on_event("hook", ("pre_tool_use", call, result))
        if result.context:
            decision.notes = [*decision.notes, f"hook: {result.context}"]
        if result.failed:
            decision.notes = [*decision.notes, f"a hook failed: {result.failed}"]
        tainted = getattr(getattr(self.permissions, "taint", None), "active", False)
        said = result.reason or "no reason given"
        if result.decision == "deny":
            return Decision("deny", f"{HOOK_REFUSAL} {said}")
        if decision.action == "allow" and (result.decision == "ask" or result.failed):
            why = f"a hook asks first: {said}" if result.decision == "ask" else "a hook failed, so it can't confirm this call"
            return Decision("ask", why, None, decision.notes)
        if result.decision == "ask" and decision.reason == CHANGES:
            decision.reason = f"a hook asks first: {said}"
        if result.decision == "allow" and decision.action == "ask" and decision.reason == CHANGES and not tainted:
            return Decision("allow", "allowed by a hook")
        return decision

    def post_hooks(self, call: ToolCall, result: str) -> str:
        """Text the post_tool_use hooks want the model to see, to append to the result ("" for none)."""
        tool = self.tools.get(call.name)
        if tool is None:
            return ""
        outcome = self.hooks.post_tool(call, tool, result) if self.hooks else None
        if outcome is None or not (outcome.context or outcome.failed):
            return ""
        self.on_event("hook", ("post_tool_use", call, outcome))
        return f"\n\n[hook] {outcome.context}" if outcome.context else ""

    def prompt_hooks(self, text: str) -> tuple[str | None, str]:
        """(a reason to stop, the message to send): user_prompt_submit hooks may block it or add context."""
        outcome = self.hooks.user_prompt(text)
        if outcome.decision or outcome.failed or outcome.context:
            self.on_event("hook", ("user_prompt_submit", None, outcome))
        if outcome.decision == "deny":
            return f"(blocked by a hook: {outcome.reason or 'no reason given'})", text
        return None, text + (f"\n\n[from a hook]\n{outcome.context}" if outcome.context else "")

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
