"""The `harness` command: settings → provider → agent → an interactive terminal session.

Run:  harness                               (after `pip install -e ".[tui]"`)
      harness --workspace C:\\some\\folder --provider anthropic

Lessons 07-23. The screen itself is drawn by harness/tui (rich when available, plain otherwise).
"""
import argparse
import sys
from pathlib import Path

from harness.agent import Agent
from harness.config import USER_DIR, ConfigError, describe, load_dotenv, load_settings
from harness.mentions import expand_mentions
from harness.providers.base import ProviderError
from harness.providers.factory import PROVIDERS, make_provider
from harness.providers.retry import RetryingProvider
from harness.tools import default_tools
from harness.tools.fs import workspace_snapshot
from harness.tui import make_ui
from harness.tui.keys import KeyWatcher
from harness.tui.prompt import LineReader
from harness.usage import CostTracker, format_cost
from harness.workspace import Workspace

# Short and direct works best for small models (see course/07-first-tools-and-repl.md).
SYSTEM_PROMPT = """You are a helpful agent. Use tools to inspect the workspace; never guess file contents.
Find files with glob, search inside them with grep, explore folders with list_dir.
To find where something is defined or used, grep for a likely word (e.g. grep 'timeout' to find a timeout setting).
Paths are relative to the workspace root. Be concise.

Workspace files (snapshot at session start; may have changed since):
{snapshot}"""


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Chat with a coding agent in your terminal.")
    # Defaults live in harness/config.py; a flag left as None means "not given" (Lesson 20).
    p.add_argument("--provider", default=None, choices=PROVIDERS, help="where the model runs")
    p.add_argument("--model", default=None, help="model name (default for ollama: qwen3:4b-instruct)")
    p.add_argument("--base-url", default=None, help="override the provider's server address")
    p.add_argument("--fallback-model", default=None,
                   help="a model (same provider) to try when the main one keeps failing")
    p.add_argument("--workspace", default="workspace", help="folder the agent works in")
    p.add_argument("--max-steps", type=int, default=None)
    p.add_argument("--yes", action="store_true",
                   help="approve every tool call without asking (only for throwaway folders)")
    p.add_argument("--no-stream", action="store_true", help="wait for whole replies instead of streaming")
    p.add_argument("--think", action="store_true", help="for thinking models: show their reasoning separately")
    p.add_argument("--plain", action="store_true", help="plain text output (no colours, Markdown or spinners)")
    p.add_argument("--show-config", action="store_true", help="print the effective settings and where each came from")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    ui, approver = make_ui(plain=args.plain, auto_approve=args.yes)

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        sys.exit(f"workspace folder not found: {workspace}")
    ws = Workspace(workspace)

    flags = {"provider": args.provider, "model": args.model, "base_url": args.base_url,
             "fallback_model": args.fallback_model, "max_steps": args.max_steps,
             "stream": False if args.no_stream else None, "think": True if args.think else None}
    try:
        _, env_warnings = load_dotenv(workspace)
        settings, warnings = load_settings(workspace, flags)
    except ConfigError as e:
        sys.exit(f"settings error: {e}")
    for warning in env_warnings + warnings:
        ui.warn(f"warning: {warning}")
    if args.show_config:
        print(describe(settings))
        return

    options = {"temperature": settings.temperature, "think": True if settings.think else None,
               "context_window": settings.context_window}
    try:
        provider = make_provider(settings.provider, settings.model, settings.base_url, **options)
        fallback = (make_provider(settings.provider, settings.fallback_model, settings.base_url, **options)
                    if settings.fallback_model else None)
    except ProviderError as e:
        sys.exit(f"error: {e}")
    provider = RetryingProvider(provider, max_retries=settings.max_retries, fallback=fallback, on_retry=ui.retry)
    costs = CostTracker(settings.provider, provider.model, settings.prices)

    def on_event(kind, data):
        if kind == "model_reply":
            costs.add(data)
        ui(kind, data)

    agent = Agent(provider, default_tools(ws, shell=settings.shell),
                  SYSTEM_PROMPT.format(snapshot=workspace_snapshot(ws)), max_steps=settings.max_steps,
                  on_event=on_event, approve=approver, stream=settings.stream)
    ui.banner("Agent harness", f"{settings.provider} · {provider.model} · {workspace}")
    reader = LineReader(ws, USER_DIR / "history", commands=["/reset", "/cost", "/bye"])
    watcher = KeyWatcher()
    approver.pause = watcher.paused
    stop_keys = "Esc or Ctrl+C stops a running task" if watcher.available else "Ctrl+C stops a running task"
    ui.info(f"/reset forget the conversation · /cost usage so far · /bye quit · @file attaches a file · {stop_keys}")
    if args.yes:
        ui.warn("--yes: every tool call runs without asking.")

    while True:
        try:
            user = reader.read(default=watcher.take_typeahead()).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user == "/bye":
            break
        if user == "/cost":
            ui.info(costs.summary())
            continue
        if user == "/reset":
            agent.reset()
            ws.forget_reads()   # the model no longer has earlier reads in its context
            ui.info("(conversation cleared)")
            continue

        message, attached = expand_mentions(user, ws)
        if attached:
            ui.info("attached: " + ", ".join(attached))
        before, cost_before = agent.usage.copy(), costs.cost()
        try:
            with watcher.watching():
                answer = agent.run(message)
        except KeyboardInterrupt:
            ui.error("cancelled")
            continue
        except ProviderError as e:
            ui.error(str(e))
            continue
        ui.answer(answer)
        turn = agent.usage - before
        cached = f" ({turn.cache_read_tokens:,} cached)" if turn.cache_read_tokens else ""
        cost_after = costs.cost()
        money = "price unknown" if cost_after is None or cost_before is None else format_cost(cost_after - cost_before)
        ui.usage_line(f"{turn.input_tokens:,} input{cached} + {turn.output_tokens:,} output tokens · {money}")

    if costs.models:
        ui.info(f"session: {costs.summary()}")


if __name__ == "__main__":
    main()
