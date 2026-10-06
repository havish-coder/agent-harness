"""Lesson 24: slash commands.

Two kinds:
- local commands run code in the app and never reach the model (/help, /cost, /model ...);
- prompt commands expand into a message for the model (/fix-tests). Users add their own as
  Markdown files: <workspace>/.harness/commands/NAME.md (project) or ~/.harness/commands/NAME.md
  (user). The file's text is the prompt; $ARGUMENTS is replaced by what follows the command.

    ---
    description: Explain a file to a beginner
    argument-hint: <file>
    ---
    Explain $ARGUMENTS to a beginner, step by step, with an example.
"""
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from harness.config import USER_DIR, describe

NAME = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass
class Command:
    name: str                                   # without the slash
    description: str
    kind: str = "local"                         # "local" or "prompt"
    run: Callable | None = None                 # local: run(session, args) -> text to show, or None
    template: str = ""                          # prompt: the message, with $ARGUMENTS / $1 $2 ...
    argument_hint: str = ""
    source: str = "built-in"                    # built-in, user or project
    aliases: tuple = ()

    def expand(self, args: str) -> str:
        """The message a prompt command sends to the model."""
        words = args.split()
        text = self.template
        if "$ARGUMENTS" not in text and not re.search(r"\$\d", text) and args:
            return f"{text.rstrip()}\n\n{args}"
        text = text.replace("$ARGUMENTS", args)
        return re.sub(r"\$(\d)", lambda m: words[int(m.group(1)) - 1] if int(m.group(1)) <= len(words) else "", text)


class CommandRegistry:
    def __init__(self):
        self.commands: dict[str, Command] = {}
        self.warnings: list[str] = []

    def add(self, command: Command) -> None:
        for name in (command.name, *command.aliases):
            self.commands[name] = command      # later sources override earlier ones on purpose

    def get(self, name: str) -> Command | None:
        return self.commands.get(name)

    def names(self) -> list[str]:
        return sorted("/" + n for n in self.commands)

    def parse(self, line: str) -> tuple[Command, str] | tuple[None, str] | None:
        """'/name args' → (command, args); unknown command → (None, name); not a command → None."""
        if not line.startswith("/") or line.startswith("//"):
            return None
        name, _, args = line[1:].partition(" ")
        command = self.commands.get(name.lower())
        return (command, args.strip()) if command else (None, name)

    def help(self) -> str:
        unique = {id(c): c for c in self.commands.values()}.values()
        lines = []
        for c in sorted(unique, key=lambda c: c.name):
            label = f"/{c.name}" + (f" {c.argument_hint}" if c.argument_hint else "")
            origin = "" if c.source == "built-in" else f"  ({c.source})"
            alias = f"  (also /{', /'.join(c.aliases)})" if c.aliases else ""
            lines.append(f"{label:<28} {c.description}{origin}{alias}")
        return "\n".join(lines)

    def load_folder(self, folder: Path, source: str) -> None:
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.md")):
            name = path.stem.lower()
            if not NAME.match(name):
                self.warnings.append(f"{path}: command names use a-z, 0-9 and '-'; skipped")
                continue
            existing = self.commands.get(name)
            if source == "project" and existing is not None and existing.source == "built-in":
                # A cloned repository must not be able to change what /reset or /help does.
                self.warnings.append(f"{path}: a project can't replace the built-in /{name}; skipped")
                continue
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            if not body.strip():
                self.warnings.append(f"{path}: empty command; skipped")
                continue
            self.add(Command(name, meta.get("description", f"custom command from {path.name}"), kind="prompt",
                             template=body.strip(), argument_hint=meta.get("argument-hint", ""), source=source))


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Optional `---` key: value `---` block at the top of a Markdown file."""
    if not text.startswith("---"):
        return {}, text
    head, sep, body = text[3:].partition("\n---")
    if not sep:
        return {}, text
    meta = {}
    for line in head.splitlines():
        key, colon, value = line.partition(":")
        if colon and key.strip():
            meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta, body.lstrip("\n")


# --- built-in commands ----------------------------------------------------------------------

def _help(session, args):
    return session.commands.help()


def _reset(session, args):
    session.reset()
    return "(conversation cleared)"


def _cost(session, args):
    return session.costs.summary()


def _config(session, args):
    return describe(session.settings)


def _model(session, args):
    if not args:
        return f"model: {session.provider.model} ({session.settings.provider})"
    session.switch_model(args)
    return f"model switched to {args}; the conversation is kept"


def _style(session, args):
    if not args:
        rows = [f"{'*' if s.name == session.style.name else ' '} {s.name:<12} {s.description}"
                + (f"  ({s.source})" if s.source != "built-in" else "") for s in session.styles.values()]
        return "\n".join(rows)
    if args not in session.styles:
        return f"unknown style '{args}'. /style lists them"
    session.set_style(args)
    return f"style: {args} (from the next reply on)"


def _mode(session, args):
    from harness.security.permissions import MODE_HELP
    if not args:
        return "\n".join(f"{'*' if m == session.permissions.mode else ' '} {m:<13} {h}" for m, h in MODE_HELP.items())
    if args not in MODE_HELP:
        return f"unknown mode '{args}'. /mode lists them"
    session.set_mode(args)
    return f"permission mode: {args} ({MODE_HELP[args]})"


def _permissions(session, args):
    """/permissions · /permissions allow|ask|deny RULE · /permissions remove RULE"""
    from harness.security.permissions import RULE_HELP, Rule, RuleError
    perms = session.permissions
    words = args.split(maxsplit=1)
    if not words:
        rows = [f"mode: {perms.mode}"]
        for action in ("deny", "ask", "allow"):
            rules = [r for r in perms.rules if r.action == action]
            if rules:
                rows.append(f"{action}:")
                rows += [f"  {r}{'  (exact)' if r.exact else ''}  ({r.source})" for r in rules]
        if len(rows) == 1:
            rows.append("no rules: reading runs, everything else asks")
        rows.append("writes to .git, .harness, editor and CI folders always ask (docs/user-guide/permissions.md)")
        return "\n".join(rows)
    if len(words) < 2 or words[0] not in ("allow", "ask", "deny", "remove"):
        return "usage: /permissions [allow|ask|deny|remove] RULE  " + RULE_HELP
    verb, text = words
    if verb == "remove":
        keep = [r for r in perms.rules if not (str(r) == text.strip() and r.source == "session")]
        if len(keep) == len(perms.rules):
            return f"no session rule {text.strip()} (rules from settings files are changed there)"
        perms.rules[:] = keep
        return f"removed {text.strip()}"
    try:
        rule = Rule.parse(text, verb, "session")
    except RuleError as e:
        return str(e)
    names = [t.name for t in session.agent.tools]
    perms.remember(rule)
    note = "" if rule.tool in names or rule.tool == "*" else f" (warning: there is no tool named {rule.tool})"
    return f"{verb} {rule} for this session{note}"


def _trust_command(trusting: bool):
    """/trust and /untrust: vouch for this folder (or stop doing so)."""
    def run(session, args):
        from harness import config
        from harness.security.trust import set_trusted
        set_trusted(session.ws.root, config.USER_DIR, trusting)
        session.audit("trust", folder=str(session.ws.root), trusted=trusting)
        session.permissions.taint.trusted = trusting
        session.refresh_hooks()
        if trusting:
            return (f"trusted: {session.ws.root}. Files you read here no longer count as untrusted content "
                    "(web pages still do)")
        return f"no longer trusted: {session.ws.root}. File text and command output now count as untrusted content"
    return run


def _hooks(session, args):
    """/hooks: every hook in the settings, and whether it runs."""
    from harness.hooks import from_entries
    everything = from_entries(session.settings.hooks)
    if not everything:
        return "no hooks. Add them under \"hooks\" in your settings (docs/user-guide/hooks.md)"
    return "\n".join(f"{'runs    ' if h in session.hooks.hooks else 'not run '} {h}" for h in everything)


def _audit(session, args):
    """/audit [N] · /audit verify"""
    from harness.audit import format_entry, verify
    log = session.audit_log
    if log is None:
        return "the audit log is off (set \"audit_log\": true in your settings to keep one)"
    if args == "verify":
        ok, count, why = verify(log.path)
        return f"{log.path}: {count} entries, chain intact" if ok else f"{log.path}: BROKEN after {count} entries: {why}"
    n = int(args) if args.isdigit() else 15
    rows = [format_entry(e) for e in log.tail(n)]
    return "\n".join([f"audit log: {log.path} (this chat is session {log.session})", *rows]) if rows else "the audit log is empty"


def _limits(session, args):
    """/limits: what this chat has used, against each limit."""
    limits, cost = session.limits, session.costs.cost()
    spent = None if cost is None else cost - session.cost_base
    minutes = (time.monotonic() - limits.started) / 60

    def row(name, used, limit):
        shown = "no limit" if limit is None else limit if isinstance(limit, str) else f"{limit:,}"
        return f"{name:<11} {used} of {shown}"
    return "\n".join([row("tool calls", limits.tool_calls, limits.max_tool_calls),
                      row("tokens", f"{limits.tokens:,}", limits.max_tokens),
                      row("cost", "price unknown" if spent is None else f"${spent:.2f}",
                          None if limits.max_cost is None else f"${limits.max_cost:.2f}"),
                      row("minutes", f"{minutes:.0f}", limits.max_minutes),
                      "Limits are per chat (/reset starts again). Change them under \"limits\" in your user or local settings."])


def _taint(session, args):
    """/taint · /taint clear"""
    taint = session.permissions.taint
    if args == "clear":
        session.audit("taint_cleared", sources=list(taint.sources))
        taint.clear()
        return "cleared: broad approvals (modes, rules for a whole tool) apply again"
    where = "trusted" if taint.trusted else "NOT trusted (/trust to trust it)"
    if not taint.active:
        return f"nothing untrusted has been read in this chat. This folder is {where}."
    listing = "\n".join(f"  {s}" for s in taint.sources)
    return (f"untrusted content read in this chat:\n{listing}\nUntil you /taint clear (or /reset), only rules "
            f"you wrote run without asking. This folder is {where}.")


def _export(session, args):
    """/export [md|tex|pdf] [file] [--last]"""
    import datetime

    from harness.export import ExportError, chat_markdown, export
    words = args.split()
    last = "--last" in words
    words = [w for w in words if w != "--last"]
    fmt = (words[0] if words else "pdf").lower().lstrip(".")
    if fmt not in ("md", "tex", "pdf"):
        return "usage: /export [md|tex|pdf] [file] [--last]"
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    target = session.ws.path(words[1]) if len(words) > 1 else session.ws.root / ".harness" / "exports" / f"chat-{stamp}"
    first = next((m.content for m in session.agent.messages if m.role == "user"), "Agent Harness chat")
    title = first.splitlines()[0][:70].replace('"', "'")
    if fmt == "pdf":
        session.ui.info("building the PDF (the first time can take a minute)...")
    try:
        written = export(chat_markdown(session.agent.messages, title, session.provider.model, last), fmt, target)
    except ExportError as e:
        return str(e)
    return f"wrote {written}"


def _tools(session, args):
    rows = []
    for tool in session.agent.tools:
        flags = []
        if callable(tool.read_only):
            flags.append("read-only for some calls")
        elif tool.read_only:
            flags.append("read-only")
        else:
            flags.append("can change things")
        if tool.concurrency_safe is True:
            flags.append("parallel")
        rows.append(f"{tool.name:<12} {', '.join(flags):<22} {tool.description.splitlines()[0]}")
    return "\n".join(rows)


# Measured (Lesson 24): without the first sentence the model ran a test file directly, got an
# import error, and "fixed" the package structure instead of the bug.
FIX_TESTS = """Fix the failing tests. Follow these steps exactly:
1. Find the project's root: use glob to find conftest.py, pyproject.toml, pytest.ini or setup.cfg.
   The folder that holds it is the project root (not its tests/ folder).
2. Run the tests from that folder with run_shell: `cd <project root> && python -m pytest -q`
   (or the command its README gives). Read the result.
3. If a test fails, the bug is in the code being tested, not in the tests, imports or project setup:
   read that code, fix it with edit_file, and run the tests again the same way as in step 2.
4. Repeat until every test passes (at most 3 rounds), then say in a few lines what you changed.
$ARGUMENTS"""

EXPLAIN = """Explain $ARGUMENTS: what it does, how the main parts fit together, and anything surprising.
Read the code first; quote line numbers."""


def builtin_commands() -> list[Command]:
    return [
        Command("help", "list the commands", run=_help),
        Command("reset", "forget the conversation and start fresh", run=_reset, aliases=("clear",)),
        Command("cost", "tokens and cost so far, per model", run=_cost),
        Command("config", "the settings in effect and where each came from", run=_config),
        Command("model", "show the model, or switch to another one", run=_model, argument_hint="[name]"),
        Command("tools", "the tools the agent can use", run=_tools),
        Command("style", "list output styles, or switch to one", run=_style, argument_hint="[name]"),
        Command("mode", "show the permission mode, or switch to another one", run=_mode, argument_hint="[mode]"),
        Command("trust", "trust this folder: its files are yours, not untrusted content", run=_trust_command(True)),
        Command("untrust", "stop trusting this folder", run=_trust_command(False)),
        Command("audit", "the audit log: recent entries, or `verify` to check it wasn't altered", run=_audit, argument_hint="[N|verify]"),
        Command("limits", "what this chat has used against its limits", run=_limits),
        Command("hooks", "the hooks in your settings, and whether each runs", run=_hooks),
        Command("taint", "what untrusted content this chat has read; clear it", run=_taint, argument_hint="[clear]"),
        Command("permissions", "the permission rules; add or remove one for this session", run=_permissions,
                argument_hint="[allow|ask|deny|remove RULE]"),
        Command("export", "save the chat (or the last answer) as Markdown, LaTeX or PDF", run=_export,
                argument_hint="[md|tex|pdf] [file] [--last]"),
        Command("bye", "quit", run=lambda session, args: None, aliases=("exit", "quit")),
        Command("fix-tests", "run the tests, fix failures, repeat until they pass", kind="prompt",
                template=FIX_TESTS, argument_hint="[what to focus on]"),
        Command("explain", "explain a file or folder", kind="prompt", template=EXPLAIN, argument_hint="@path"),
    ]


def load_commands(workspace: Path) -> CommandRegistry:
    """Built-ins, then ~/.harness/commands, then <workspace>/.harness/commands (later wins)."""
    registry = CommandRegistry()
    for command in builtin_commands():
        registry.add(command)
    registry.load_folder(USER_DIR / "commands", "user")
    registry.load_folder(workspace / ".harness" / "commands", "project")
    return registry
