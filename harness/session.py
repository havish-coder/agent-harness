"""Lessons 24-25: one running session: settings, workspace, provider, agent, costs, style and the UI.

Interfaces (the terminal now, the web server later) build a Session and talk to it; commands
receive it so they can act on the running app (switch the model, show costs, reset).
"""
import datetime
import json
import subprocess
import uuid

from harness import config
from harness.agent import Agent
from harness.audit import AuditLog
from harness.chats import Chat, ChatInfo, ChatStore, Replay, replay, title_from
from harness.config import Settings
from harness.context.prompt import PROMPT_SHARE, Assembly, Section, assemble, environment_text
from harness.context.tokens import ContextBudget, estimate_tokens
from harness.context.windows import window_for
from harness.hooks import Hooks, from_entries
from harness.limits import Limits
from harness.providers.factory import make_provider
from harness.providers.retry import RetryingProvider
from harness.security.permissions import MODES, Permissions
from harness.security.sandbox import detect as detect_sandbox
from harness.security.sandbox import hint as sandbox_hint
from harness.security.taint import SYSTEM_RULE
from harness.security.trust import is_trusted
from harness.styles import BUILTIN, Style
from harness.tools import default_tools
from harness.tools.fs import workspace_snapshot
from harness.tools.shell import detect_shell
from harness.usage import CostTracker, format_cost
from harness.workspace import Workspace

# Short and direct works best for small models (see course/07-first-tools-and-repl.md).
ROLE = """You are a helpful agent. Use tools to inspect the workspace; never guess file contents.
Find files with glob, search inside them with grep, explore folders with list_dir.
To find where something is defined or used, grep for a likely word (e.g. grep 'timeout' to find a timeout setting).
Paths are relative to the workspace root. Be concise."""
WORKSPACE_HEADER = "Workspace files (snapshot at session start; may have changed since):"
LISTING_LINES = 50            # the longest workspace listing in the prompt; a small window shrinks it
# Said only when old results may be cleared (Lesson 38): what a note means, and the one thing the model can do about it.
CLEARING_RULE = ("When the window fills, old tool results are replaced by a note starting '[cleared to save space'. "
                 "Before you move on from a result you will need later, write down what you need from it in your reply.")
SYSTEM_PROMPT = ROLE + "\n\n" + WORKSPACE_HEADER + "\n{snapshot}"   # the whole prompt in one string: for scripts and recordings


class Session:
    def __init__(self, settings: Settings, ws: Workspace, ui, approver, styles: dict[str, Style] | None = None):
        self.settings, self.ws, self.ui, self.approver = settings, ws, ui, approver
        self.styles = styles or {s.name: s for s in BUILTIN}
        if settings.output_style not in self.styles:
            ui.warn(f"warning: unknown output style '{settings.output_style}'; using default")
            settings.output_style = "default"
        self.style = self.styles[settings.output_style]
        self.reported_tokens = 0         # what the model server last said it read
        self.store = ChatStore(config.USER_DIR, ws.root) if settings.save_chats else None    # saved chats (Lesson 40)
        self.chat: Chat | None = None    # the saved chat this conversation is written to; made on the first message
        if self.store is not None:
            self.store.cleanup(settings.chat_retention_days)
        self.provider = RetryingProvider(self.make_provider(settings.model), max_retries=settings.max_retries,
                                         fallback=self.make_provider(settings.fallback_model)
                                         if settings.fallback_model else None,
                                         on_retry=ui.retry)
        self.costs = CostTracker(settings.provider, self.provider.model, settings.prices)
        self.permissions = Permissions.from_settings(ws, settings.permission_mode, settings.permissions)
        self.permissions.taint.trusted = is_trusted(ws.root, config.USER_DIR)
        self.sandbox = detect_sandbox() if settings.sandbox != "off" else None
        required = settings.sandbox == "on" and self.sandbox is None
        if required:
            ui.warn(f"warning: sandbox is \"on\" but this machine has none, so commands are refused ({sandbox_hint()})")
        tools = default_tools(ws, shell=settings.shell, env_keep=settings.shell_env_keep, web=settings.web_fetch,
                              web_allow_local=settings.web_allow_local, sandbox=self.sandbox,
                              sandbox_network=settings.sandbox_network, sandbox_required=required)
        for warning in self.permissions.unknown_tools([t.name for t in tools]):
            ui.warn(f"warning: {warning}")
        self.hooks = Hooks([], ws.root, self.permissions, settings.shell_env_keep)
        self.refresh_hooks(announce=True)
        lim = settings.limits
        self.limits = Limits(lim.get("tool_calls"), lim.get("cost"), lim.get("tokens"), lim.get("minutes"))
        self.cost_base = 0.0                   # the money spent before this chat started (after /reset)
        self.session_id = uuid.uuid4().hex[:8]
        month = datetime.date.today().strftime("%Y-%m")
        self.audit_log = AuditLog(config.USER_DIR / "audit" / f"{month}.jsonl", self.session_id) if settings.audit_log else None
        self._audit_warned = False
        window = window_for(settings.provider, self.provider.model, settings.context_window,
                            settings.sources.get("context_window", "default") != "default")
        self.context = ContextBudget(window, reserve=min(settings.max_output_tokens, window // 4))
        self.shell_name = detect_shell(settings.shell).name
        self.prompt = self.build_prompt()
        self.agent = Agent(self.provider, tools,
                           self.prompt.text, max_steps=settings.max_steps,
                           on_event=self.on_event, approve=approver, stream=settings.stream,
                           permissions=self.permissions, fence_untrusted=settings.fence_untrusted,
                           hooks=self.hooks, redact_results=settings.redact_secrets, limit_check=self.limit_reason,
                           context=self.context, microcompact=settings.microcompact,
                           keep_recent=settings.microcompact_keep, auto_compact=settings.auto_compact)
        self._status_error_shown = False
        self.audit("session", workspace=str(ws.root), provider=settings.provider, model=self.provider.model,
                   mode=self.permissions.mode, trusted=self.permissions.taint.trusted, tools=[t.name for t in tools],
                   sandbox=self.sandbox.name if self.sandbox else None,
                   hooks=len(self.hooks.hooks))

    def make_provider(self, model: str | None):
        s = self.settings
        return make_provider(s.provider, model, s.base_url, temperature=s.temperature,
                             think=True if s.think else None, context_window=s.context_window,
                             max_output_tokens=s.max_output_tokens)

    def on_event(self, kind, data):
        if kind == "model_reply":
            self.costs.add(data)
            self.reported_tokens = data.usage.input_tokens
            self.limits.tokens += data.usage.input_tokens + data.usage.output_tokens
        elif kind == "tool_call":
            self.limits.tool_calls += 1        # every call the model asks for, run or refused
        elif kind in ("microcompact", "compact"):
            self.ws.forget_reads()             # those results left the conversation: reading them again must return the text, not "unchanged"
        if kind in ("message", "rolled_back", "microcompact", "compact"):
            self.save_event(kind, data)
        self.record(kind, data)
        self.ui(kind, data)

    # --- limits and the audit log (Lesson 34) ---------------------------------------------------
    def limit_reason(self) -> str | None:
        cost = self.costs.cost()
        return self.limits.exceeded(cost=None if cost is None else cost - self.cost_base)

    def audit(self, kind: str, **fields) -> None:
        """One line in the audit log (a no-op when it's off). A log that can't be written is reported once."""
        if self.audit_log is None:
            return
        self.audit_log.write(kind, **fields)
        if self.audit_log.failed and not self._audit_warned:
            self._audit_warned = True
            self.ui.warn(f"warning: the audit log can't be written ({self.audit_log.path}); the agent keeps working")

    def record(self, kind: str, data) -> None:
        """Turn agent events into audit entries: what was decided, approved, run, hidden, stopped."""
        if self.audit_log is None:
            return
        if kind == "permission":
            call, decision = data
            tool = self.agent.tools.get(call.name)
            subject = call.arguments.get(tool.subject) if tool is not None and tool.subject else call.arguments
            self.audit("decision", tool=call.name, subject=subject, action=decision.action, reason=decision.reason,
                       notes=decision.notes or None)
        elif kind == "tool_approved":
            self.audit("approved", tool=data[0].name, answer=data[1] if isinstance(data[1], str) else "yes")
        elif kind == "tool_denied":
            self.audit("user_denied", tool=data.name)
        elif kind == "tool_result":
            call, result = data
            self.audit("result", tool=call.name, chars=len(result), error=result.startswith("Error") or None)
        elif kind == "redacted":
            self.audit("redacted", tool=data[0].name, kinds=data[1])
        elif kind == "hook":
            event, call, outcome = data
            self.audit("hook", hook=event, tool=call.name if call else None,
                       command=outcome.hook.command if outcome.hook else None, decision=outcome.decision,
                       failed=outcome.failed)
        elif kind == "model_reply":
            self.audit("model", model=data.model or self.provider.model, input_tokens=data.usage.input_tokens,
                       output_tokens=data.usage.output_tokens, stop=data.stop_reason)
        elif kind == "limit":
            self.audit("limit", why=data)
        elif kind == "microcompact":
            self.audit("microcompact", tools=[c.tool for c in data.cleared], saved_tokens=data.saved)
        elif kind == "compact":
            self.audit("compact", removed=data.removed, tokens_before=data.before, tokens_after=data.after, fenced=data.fenced)
        elif kind == "compact_failed":
            self.audit("compact_failed", why=data)

    # --- saved chats (Lesson 40) -----------------------------------------------------------------
    def save_event(self, kind: str, data) -> None:
        """Write what just happened to this chat's log: a message, or a change made to the conversation."""
        if self.store is None:
            return
        try:
            if kind == "message":
                if self.chat is None:
                    self.chat = self.store.new(self.provider.model)
                    self.store.register()
                if not self.chat.title and data.role == "user":
                    self.chat.rename(title_from(data.content))
                self.chat.message(data)
            elif self.chat is not None:
                if kind == "rolled_back":
                    self.chat.rollback(data)
                elif kind == "microcompact":
                    self.chat.clear([c.call_id for c in data.cleared])
                elif kind == "compact":
                    self.chat.compact(data.removed, self.agent.messages[1])
        except OSError as e:
            self.store = None
            self.ui.warn(f"warning: this chat can't be saved ({e}); the agent keeps working")

    def chats(self) -> list[ChatInfo]:
        return self.store.infos() if self.store is not None else []

    def resume(self, info: ChatInfo) -> Replay:
        """Continue a saved chat: the conversation is rebuilt from its log, and new messages are added to the same log."""
        assert self.store is not None
        found = replay(info.path)
        self.reset()
        self.agent.messages[1:] = found.messages
        self.agent.archive = list(found.archive)
        self.agent.compactions = found.compactions
        taint = self.permissions.taint
        for source in found.untrusted:                  # it read untrusted content before: it still counts (Lesson 31)
            if source not in taint.sources:
                taint.sources.append(source)
        self.chat = self.store.open(info)
        self.chat.title = found.title or info.title
        if found.dropped:
            self.chat.rollback(len(found.messages))     # the log agrees with what was restored
        return found

    def fork(self, title: str | None = None) -> Chat | None:
        """A new chat that starts as a copy of this one; this conversation carries on in the copy."""
        if self.store is None or self.chat is None or not self.chat.path.exists():
            return None
        name = (title or "").strip() or f"{self.chat.title or 'chat'} (fork)"
        self.chat = self.store.fork(self.chat, self.provider.model, name)
        return self.chat

    def close(self) -> None:
        """The chat is over: record the totals."""
        cost = self.costs.cost()
        self.audit("end", tool_calls=self.limits.tool_calls, tokens=self.limits.tokens,
                   cost=None if cost is None else round(cost, 6))

    def set_style(self, name: str) -> None:
        """Change how the agent writes, from the next model call on. The conversation is kept."""
        self.style = self.styles[name]
        self.settings.output_style = name
        self.settings.sources["output_style"] = "command"
        self.rebuild_prompt()

    def build_prompt(self) -> Assembly:
        """The system prompt from its sections, most stable first, within a share of the window (Lesson 37)."""
        ws = self.ws
        files = f"{WORKSPACE_HEADER}\n{workspace_snapshot(ws, limit=LISTING_LINES)}"
        per_line = max(1.0, estimate_tokens(files) / max(1, files.count("\n")))    # long names cost more per line

        def listing(max_tokens: int) -> str:
            return f"{WORKSPACE_HEADER}\n{workspace_snapshot(ws, limit=max(5, int(max_tokens / per_line)))}"
        sections = [Section("role", ROLE, 0)]
        if self.settings.fence_untrusted:
            sections.append(Section("untrusted content", SYSTEM_RULE, 1))
        if self.settings.microcompact:
            sections.append(Section("clearing rule", CLEARING_RULE, 1))
        if self.style.prompt:
            sections.append(Section("output style", f"# Output style: {self.style.name}\n{self.style.prompt}", 1, required=False))
        sections.append(Section("environment", environment_text(ws.root, self.shell_name), 2, required=False))
        sections.append(Section("workspace files", files, 2, required=False, shrink=listing))
        return assemble(sections, budget=max(600, int(self.context.window * PROMPT_SHARE)))

    def rebuild_prompt(self) -> None:
        """Assemble the prompt again (after a style change) and put it in the running conversation."""
        self.prompt = self.build_prompt()
        self.agent.system_prompt = self.prompt.text
        self.agent.messages[0].content = self.prompt.text

    def refresh_hooks(self, announce: bool = False) -> None:
        """Choose the hooks that run (Lesson 33). A project's hooks run only in a trusted folder; when
        they don't, say which were left out."""
        everything = from_entries(self.settings.hooks)
        trusted = self.permissions.taint.trusted
        self.hooks.hooks = [h for h in everything if h.source != "project" or trusted]
        skipped = [h for h in everything if h not in self.hooks.hooks]
        if skipped and announce:
            self.ui.warn(f"warning: {len(skipped)} hook(s) from this project's settings were not run because the folder "
                         "isn't trusted (a hook is a program). /hooks lists them; /trust if the project is yours.")

    def set_mode(self, mode: str) -> None:
        """Switch the permission mode (Lesson 29); rules and the conversation are kept."""
        if mode not in MODES:
            raise ValueError(f"unknown mode '{mode}'; choose from {', '.join(MODES)}")
        self.audit("mode", before=self.permissions.mode, after=mode)
        self.permissions.mode = self.settings.permission_mode = mode
        self.settings.sources["permission_mode"] = "command"

    def estimate_context(self) -> int:
        """Tokens in the conversation as it stands now (an estimate, Lesson 36)."""
        return self.context.check(self.agent.messages, self.agent.tools.schemas()).estimated

    # --- the status line (Lesson 25) ------------------------------------------------------------
    def status(self) -> dict:
        cost = self.costs.cost()
        return {"provider": self.settings.provider, "model": self.provider.model,
                "context_tokens": self.estimate_context(),
                "context_window": self.context.window,
                "cost": None if cost is None else round(cost, 6), "style": self.style.name,
                "mode": self.permissions.mode,
                "workspace": str(self.ws.root), "turns": sum(m.role == "user" for m in self.agent.messages)}

    def status_text(self) -> str:
        """One line under the prompt: the user's own command if set, else the built-in summary."""
        info = self.status()
        if self.settings.status_line:
            custom = self.run_status_command(info)
            if custom is not None:
                return custom
        window = info["context_window"]
        context = f"~{info['context_tokens'] / 1000:.1f}k"
        if window:
            context += f"/{window / 1000:.1f}k ({100 * info['context_tokens'] // window}%)"
        money = "price unknown" if info["cost"] is None else format_cost(info["cost"])
        parts = [info["model"], f"context {context}", money]
        if info["style"] != "default":
            parts.append(f"style {info['style']}")
        if info["mode"] != "default":
            parts.append(f"mode {info['mode']}")
        return " · ".join(parts)

    def run_status_command(self, info: dict) -> str | None:
        """Run the status_line command with the status as JSON on stdin; show its first line."""
        try:
            done = subprocess.run(self.settings.status_line, shell=True, input=json.dumps(info), text=True,
                                  capture_output=True, timeout=2, cwd=self.ws.root)
            line = (done.stdout.strip().splitlines() or [""])[0]
            return line[:200] if done.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            if not self._status_error_shown:
                self.ui.warn("warning: the status_line command failed or took longer than 2 s")
                self._status_error_shown = True
            return None

    def switch_model(self, model: str) -> None:
        """Keep the conversation, change the model (same provider)."""
        self.provider.inner = self.make_provider(model)
        self.settings.model = model
        self.settings.sources["model"] = "command"

    def reset(self) -> None:
        self.agent.reset()
        self.chat = None                 # the next message starts a new saved chat; this one stays as it was
        self.limits.reset()
        self.cost_base = self.costs.cost() or 0.0
        self.permissions.taint.clear()   # a new conversation has read nothing yet
        self.ws.forget_reads()   # the model no longer has earlier reads in its context
