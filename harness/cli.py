"""The `harness` command: settings → session → an interactive terminal loop.

Run:  harness                               (after `pip install -e ".[tui]"`)
      harness --workspace C:\\some\\folder --provider anthropic

Lessons 07-25. The screen is drawn by harness/tui (rich when available, plain otherwise); the
running app is a harness.session.Session; slash commands live in harness/commands.py.
"""
import argparse
import sys
from pathlib import Path

from harness.commands import Send, load_commands, resume_text
from harness.config import USER_DIR, ConfigError, describe, load_dotenv, load_settings
from harness.mentions import expand_mentions
from harness.providers.base import ProviderError
from harness.providers.factory import PROVIDERS
from harness.security.permissions import MODE_HELP, MODES
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
    p.add_argument("--mode", default=None, choices=MODES,
                   help="permission mode: " + "; ".join(f"{m}: {h}" for m, h in MODE_HELP.items()))
    p.add_argument("--yes", action="store_true",
                   help="same as --mode bypass: run tool calls without asking (only for throwaway folders)")
    p.add_argument("--no-stream", action="store_true", help="wait for whole replies instead of streaming")
    p.add_argument("--think", action="store_true", help="for thinking models: show their reasoning separately")
    p.add_argument("--plain", action="store_true", help="plain text output (no colours, Markdown or spinners)")
    p.add_argument("--show-config", action="store_true", help="print the effective settings and where each came from")
    p.add_argument("-c", "--continue", dest="continue_chat", action="store_true",
                   help="carry on with the most recent chat in this folder")
    p.add_argument("-r", "--resume", nargs="?", const="", default=None, metavar="CHAT",
                   help="carry on with a saved chat: its number in /chats, a word from its title, or the start of its id "
                        "(with no value: choose from a list)")
    p.add_argument("--no-save", action="store_true", help="don't save this conversation")
    p.add_argument("--fresh", action="store_true", help="don't read the project's progress journal this time")
    return p.parse_args(argv)


def choose_chat(session: Session, ref: str | None, latest: bool, ui):
    """The chat the user asked to resume at start-up, or None (with a message saying why)."""
    store = session.store
    if store is None:
        ui.warn("chats aren't being saved, so there is nothing to resume")
        return None
    if latest:
        info = store.latest()
        if info is None:
            ui.info("no earlier chat in this folder; starting a new one")
        return info
    if ref:
        info = store.find(ref)
        if info is None:
            ui.warn(f"no single saved chat matches '{ref}'; starting a new one. /chats lists them")
        return info
    infos = store.infos()
    if not infos:
        ui.info("no earlier chat in this folder; starting a new one")
        return None
    for n, i in enumerate(infos[:15], 1):
        ui.info(f"  {n:>2}  {i.age():<12} {i.messages:>4} msgs  {i.title or '(no title)'}")
    try:
        picked = input("resume which chat? (number, or Enter for a new one) ").strip()
    except EOFError:
        return None
    return store.find(picked) if picked else None


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
    info = session.status()
    window = info["context_window"]
    context = f" · context ~{100 * info['context_tokens'] // window}%" if window else ""
    ui.usage_line(f"{turn.input_tokens:,} input{cached} + {turn.output_tokens:,} output tokens · {money}{context}")
    session.after_turn(getattr(ui, "ask_choice", None))        # keep the progress journal up to date, or offer one (Lesson 42b)


def main(argv=None):
    args = parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    ui, approver = make_ui(plain=args.plain)

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        sys.exit(f"workspace folder not found: {workspace}")

    flags = {"provider": args.provider, "model": args.model, "base_url": args.base_url,
             "fallback_model": args.fallback_model, "max_steps": args.max_steps,
             "stream": False if args.no_stream else None, "think": True if args.think else None,
             "permission_mode": "bypass" if args.yes else args.mode, "save_chats": False if args.no_save else None}
    try:
        _, env_warnings = load_dotenv(workspace)
        settings, warnings = load_settings(workspace, flags)
    except ConfigError as e:
        sys.exit(f"settings error: {e}")
    # Relative folders are relative to the workspace, like every other path the agent uses.
    ws = Workspace(workspace, extra_dirs=[workspace / Path(d).expanduser() for d in settings.additional_directories])
    commands = load_commands(workspace)
    styles, style_warnings = load_styles(workspace)
    for warning in env_warnings + warnings + commands.warnings + style_warnings:
        ui.warn(f"warning: {warning}")
    if args.show_config:
        print(describe(settings))
        return

    try:
        session = Session(settings, ws, ui, approver, styles, interface="terminal", fresh=args.fresh)
    except ProviderError as e:
        sys.exit(f"error: {e}")
    session.commands = commands
    reader = LineReader(ws, USER_DIR / "history", commands=commands.names())
    watcher = KeyWatcher()
    approver.pause = watcher.paused

    stop_keys = "Esc or Ctrl+C stops a running task" if watcher.available else "Ctrl+C stops a running task"
    ui.banner("Agent harness", f"{settings.provider} · {session.provider.model} · {workspace}")
    ui.info(f"/help commands · @file attaches a file · {stop_keys}")
    banner = session.journal_banner()
    if banner:
        ui.info(banner)
    if args.continue_chat or args.resume is not None:
        info = choose_chat(session, args.resume, args.continue_chat, ui)
        if info is not None:
            ui.info(resume_text(session, info))
    if session.sandbox is not None:
        ui.info(session.sandbox.describe(settings.sandbox_network))
    if settings.permission_mode != "default":
        ui.warn(f"permission mode {settings.permission_mode}: {MODE_HELP[settings.permission_mode]}")
    broad = settings.permission_mode in ("accept-edits", "bypass") or any(
        e["action"] == "allow" and "(" not in e["rule"] for e in settings.permissions)
    if broad and not session.permissions.taint.trusted:
        ui.warn("this folder isn't trusted: after the agent reads files or runs commands here, only rules "
                "with a pattern run without asking. /trust if the files are yours.")
    if any(not f.trusted for f in session.memory):
        names = ", ".join(f.label for f in session.memory if not f.trusted)
        ui.warn(f"{names} found, but this folder isn't trusted, so the agent reads it as information and not as your "
                "instructions. /trust if you wrote it; /memory shows what was read.")

    while True:
        session.announce_tasks()                 # background tasks that ended while you were thinking (Lesson 48)
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
            if isinstance(output, Send):                    # the command also has a request for the agent (Lesson 45)
                if output.notice:
                    ui.info(output.notice)
                run_turn(session, watcher, str(output))
            elif output:
                ui.info(output)
        else:
            run_turn(session, watcher, command.expand(rest))

    session.close()
    if session.costs.models:
        ui.info(f"session: {session.costs.summary()}")


if __name__ == "__main__":
    main()
