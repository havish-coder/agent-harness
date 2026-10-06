"""The `harness` command: settings → session → an interactive terminal loop.

Run:  harness                               (after `pip install -e ".[tui]"`)
      harness --workspace C:\\some\\folder --provider anthropic

Lessons 07-25. The screen is drawn by harness/tui (rich when available, plain otherwise); the
running app is a harness.session.Session; slash commands live in harness/commands.py.
"""
import argparse
import sys
from pathlib import Path

from harness.commands import load_commands
from harness.config import USER_DIR, ConfigError, describe, load_dotenv, load_settings
from harness.mentions import expand_mentions
from harness.providers.base import ProviderError
from harness.providers.factory import PROVIDERS
from harness.session import SYSTEM_PROMPT, Session
from harness.styles import load_styles
from harness.tui import make_ui
from harness.tui.keys import KeyWatcher
from harness.tui.prompt import LineReader
from harness.usage import format_cost
from harness.workspace import Workspace

__all__ = ["SYSTEM_PROMPT", "main"]


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


def run_turn(session: Session, watcher: KeyWatcher, message: str) -> None:
    """Send one message to the agent and show the result and its cost."""
    ui, agent, costs = session.ui, session.agent, session.costs
    message, attached = expand_mentions(message, session.ws)
    if attached:
        ui.info("attached: " + ", ".join(attached))
    before, cost_before = agent.usage.copy(), costs.cost()
    try:
        with watcher.watching():
            answer = agent.run(message)
    except KeyboardInterrupt:
        ui.error("cancelled")
        return
    except ProviderError as e:
        ui.error(str(e))
        return
    ui.answer(answer)
    turn = agent.usage - before
    cached = f" ({turn.cache_read_tokens:,} cached)" if turn.cache_read_tokens else ""
    cost_after = costs.cost()
    money = "price unknown" if cost_after is None or cost_before is None else format_cost(cost_after - cost_before)
    window = session.status()["context_window"]
    context = f" · context {100 * session.context_tokens // window}%" if window else ""
    ui.usage_line(f"{turn.input_tokens:,} input{cached} + {turn.output_tokens:,} output tokens · {money}{context}")


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
    commands = load_commands(workspace)
    styles, style_warnings = load_styles(workspace)
    for warning in env_warnings + warnings + commands.warnings + style_warnings:
        ui.warn(f"warning: {warning}")
    if args.show_config:
        print(describe(settings))
        return

    try:
        session = Session(settings, ws, ui, approver, styles)
    except ProviderError as e:
        sys.exit(f"error: {e}")
    session.commands = commands
    reader = LineReader(ws, USER_DIR / "history", commands=commands.names())
    watcher = KeyWatcher()
    approver.pause = watcher.paused

    stop_keys = "Esc or Ctrl+C stops a running task" if watcher.available else "Ctrl+C stops a running task"
    ui.banner("Agent harness", f"{settings.provider} · {session.provider.model} · {workspace}")
    ui.info(f"/help commands · @file attaches a file · {stop_keys}")
    if args.yes:
        ui.warn("--yes: every tool call runs without asking.")

    while True:
        try:
            # The status line is computed once per prompt: the toolbar redraws on every keystroke.
            line = reader.read(default=watcher.take_typeahead(), toolbar=session.status_text()).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        parsed = commands.parse(line)
        if parsed is None:
            run_turn(session, watcher, line[1:] if line.startswith("//") else line)   # //x sends "/x"
            continue
        command, rest = parsed
        if command is None:
            ui.warn(f"unknown command /{rest}. /help lists them; start with // to send a message beginning with /")
        elif command.name == "bye":
            break
        elif command.kind == "local":
            output = command.run(session, rest)
            if output:
                ui.info(output)
        else:
            run_turn(session, watcher, command.expand(rest))

    if session.costs.models:
        ui.info(f"session: {session.costs.summary()}")


if __name__ == "__main__":
    main()
