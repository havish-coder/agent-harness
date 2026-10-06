"""Lesson 24: one running session: settings, workspace, provider, agent, costs and the UI.

Interfaces (the terminal now, the web server later) build a Session and talk to it; commands
receive it so they can act on the running app (switch the model, show costs, reset).
"""
from harness.agent import Agent
from harness.config import Settings
from harness.providers.factory import make_provider
from harness.providers.retry import RetryingProvider
from harness.tools import default_tools
from harness.tools.fs import workspace_snapshot
from harness.usage import CostTracker
from harness.workspace import Workspace

# Short and direct works best for small models (see course/07-first-tools-and-repl.md).
SYSTEM_PROMPT = """You are a helpful agent. Use tools to inspect the workspace; never guess file contents.
Find files with glob, search inside them with grep, explore folders with list_dir.
To find where something is defined or used, grep for a likely word (e.g. grep 'timeout' to find a timeout setting).
Paths are relative to the workspace root. Be concise.

Workspace files (snapshot at session start; may have changed since):
{snapshot}"""


class Session:
    def __init__(self, settings: Settings, ws: Workspace, ui, approver):
        self.settings, self.ws, self.ui, self.approver = settings, ws, ui, approver
        self.provider = RetryingProvider(self.make_provider(settings.model), max_retries=settings.max_retries,
                                         fallback=self.make_provider(settings.fallback_model)
                                         if settings.fallback_model else None,
                                         on_retry=ui.retry)
        self.costs = CostTracker(settings.provider, self.provider.model, settings.prices)
        self.agent = Agent(self.provider, default_tools(ws, shell=settings.shell),
                           SYSTEM_PROMPT.format(snapshot=workspace_snapshot(ws)), max_steps=settings.max_steps,
                           on_event=self.on_event, approve=approver, stream=settings.stream)

    def make_provider(self, model: str | None):
        s = self.settings
        return make_provider(s.provider, model, s.base_url, temperature=s.temperature,
                             think=True if s.think else None, context_window=s.context_window)

    def on_event(self, kind, data):
        if kind == "model_reply":
            self.costs.add(data)
        self.ui(kind, data)

    def switch_model(self, model: str) -> None:
        """Keep the conversation, change the model (same provider)."""
        self.provider.inner = self.make_provider(model)
        self.settings.model = model
        self.settings.sources["model"] = "command"

    def reset(self) -> None:
        self.agent.reset()
        self.ws.forget_reads()   # the model no longer has earlier reads in its context
