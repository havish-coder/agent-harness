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
from harness.config import Settings
from harness.hooks import Hooks, from_entries
from harness.limits import Limits
from harness.providers.factory import make_provider
from harness.providers.retry import RetryingProvider
from harness.security.permissions import MODES, Permissions
from harness.security.taint import SYSTEM_RULE
from harness.security.trust import is_trusted
from harness.styles import BUILTIN, Style, apply_style
from harness.tools import default_tools
from harness.tools.fs import workspace_snapshot
from harness.usage import CostTracker, format_cost
from harness.workspace import Workspace

# Short and direct works best for small models (see course/07-first-tools-and-repl.md).
SYSTEM_PROMPT = """You are a helpful agent. Use tools to inspect the workspace; never guess file contents.
Find files with glob, search inside them with grep, explore folders with list_dir.
To find where something is defined or used, grep for a likely word (e.g. grep 'timeout' to find a timeout setting).
Paths are relative to the workspace root. Be concise.

Workspace files (snapshot at session start; may have changed since):
{snapshot}"""


class Session:
    def __init__(self, settings: Settings, ws: Workspace, ui, approver, styles: dict[str, Style] | None = None):
        self.settings, self.ws, self.ui, self.approver = settings, ws, ui, approver
        self.styles = styles or {s.name: s for s in BUILTIN}
        if settings.output_style not in self.styles:
            ui.warn(f"warning: unknown output style '{settings.output_style}'; using default")
            settings.output_style = "default"
        self.style = self.styles[settings.output_style]
        self.base_prompt = SYSTEM_PROMPT.format(snapshot=workspace_snapshot(ws))
        if settings.fence_untrusted:
            self.base_prompt += "\n\n" + SYSTEM_RULE
        self.context_tokens = 0          # size of the conversation at the last model call
        self.provider = RetryingProvider(self.make_provider(settings.model), max_retries=settings.max_retries,
                                         fallback=self.make_provider(settings.fallback_model)
                                         if settings.fallback_model else None,
                                         on_retry=ui.retry)
        self.costs = CostTracker(settings.provider, self.provider.model, settings.prices)
        self.permissions = Permissions.from_settings(ws, settings.permission_mode, settings.permissions)
        self.permissions.taint.trusted = is_trusted(ws.root, config.USER_DIR)
        tools = default_tools(ws, shell=settings.shell, env_keep=settings.shell_env_keep, web=settings.web_fetch,
                              web_allow_local=settings.web_allow_local)
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
        self.agent = Agent(self.provider, tools,
                           apply_style(self.base_prompt, self.style), max_steps=settings.max_steps,
                           on_event=self.on_event, approve=approver, stream=settings.stream,
                           permissions=self.permissions, fence_untrusted=settings.fence_untrusted,
                           hooks=self.hooks, redact_results=settings.redact_secrets, limit_check=self.limit_reason)
        self._status_error_shown = False
        self.audit("session", workspace=str(ws.root), provider=settings.provider, model=self.provider.model,
                   mode=self.permissions.mode, trusted=self.permissions.taint.trusted, tools=[t.name for t in tools],
                   hooks=len(self.hooks.hooks))

    def make_provider(self, model: str | None):
        s = self.settings
        return make_provider(s.provider, model, s.base_url, temperature=s.temperature,
                             think=True if s.think else None, context_window=s.context_window,
                             max_output_tokens=s.max_output_tokens)

    def on_event(self, kind, data):
        if kind == "model_reply":
            self.costs.add(data)
            self.context_tokens = data.usage.input_tokens + data.usage.output_tokens
            self.limits.tokens += data.usage.input_tokens + data.usage.output_tokens
        elif kind == "tool_call":
            self.limits.tool_calls += 1        # every call the model asks for, run or refused
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
        self.agent.system_prompt = apply_style(self.base_prompt, self.style)
        self.agent.messages[0].content = self.agent.system_prompt

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

    # --- the status line (Lesson 25) ------------------------------------------------------------
    def status(self) -> dict:
        cost = self.costs.cost()
        return {"provider": self.settings.provider, "model": self.provider.model,
                "context_tokens": self.context_tokens,
                "context_window": self.settings.context_window if self.settings.provider == "ollama" else None,
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
        context = f"{info['context_tokens'] / 1000:.1f}k"
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
        self.limits.reset()
        self.cost_base = self.costs.cost() or 0.0
        self.permissions.taint.clear()   # a new conversation has read nothing yet
        self.ws.forget_reads()   # the model no longer has earlier reads in its context
