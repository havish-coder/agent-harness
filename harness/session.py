"""Lessons 24-25: one running session: settings, workspace, provider, agent, costs, style and the UI.

Interfaces (the terminal now, the web server later) build a Session and talk to it; commands
receive it so they can act on the running app (switch the model, show costs, reset).
"""
import json
import subprocess

from harness.agent import Agent
from harness.config import Settings
from harness.providers.factory import make_provider
from harness.providers.retry import RetryingProvider
from harness.security.permissions import MODES, Permissions
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
        self.context_tokens = 0          # size of the conversation at the last model call
        self.provider = RetryingProvider(self.make_provider(settings.model), max_retries=settings.max_retries,
                                         fallback=self.make_provider(settings.fallback_model)
                                         if settings.fallback_model else None,
                                         on_retry=ui.retry)
        self.costs = CostTracker(settings.provider, self.provider.model, settings.prices)
        self.permissions = Permissions.from_settings(ws, settings.permission_mode, settings.permissions)
        tools = default_tools(ws, shell=settings.shell)
        for warning in self.permissions.unknown_tools([t.name for t in tools]):
            ui.warn(f"warning: {warning}")
        self.agent = Agent(self.provider, tools,
                           apply_style(self.base_prompt, self.style), max_steps=settings.max_steps,
                           on_event=self.on_event, approve=approver, stream=settings.stream,
                           permissions=self.permissions)
        self._status_error_shown = False

    def make_provider(self, model: str | None):
        s = self.settings
        return make_provider(s.provider, model, s.base_url, temperature=s.temperature,
                             think=True if s.think else None, context_window=s.context_window,
                             max_output_tokens=s.max_output_tokens)

    def on_event(self, kind, data):
        if kind == "model_reply":
            self.costs.add(data)
            self.context_tokens = data.usage.input_tokens + data.usage.output_tokens
        self.ui(kind, data)

    def set_style(self, name: str) -> None:
        """Change how the agent writes, from the next model call on. The conversation is kept."""
        self.style = self.styles[name]
        self.settings.output_style = name
        self.settings.sources["output_style"] = "command"
        self.agent.system_prompt = apply_style(self.base_prompt, self.style)
        self.agent.messages[0].content = self.agent.system_prompt

    def set_mode(self, mode: str) -> None:
        """Switch the permission mode (Lesson 29); rules and the conversation are kept."""
        if mode not in MODES:
            raise ValueError(f"unknown mode '{mode}'; choose from {', '.join(MODES)}")
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
        self.ws.forget_reads()   # the model no longer has earlier reads in its context
