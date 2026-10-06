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


def _tools(session, args):
    rows = []
    for tool in session.agent.tools:
        flags = []
        if callable(tool.read_only):
            flags.append("read-only for some calls")
        elif tool.read_only:
            flags.append("read-only")
        else:
            flags.append("asks first")
        if tool.concurrency_safe is True:
            flags.append("parallel")
        rows.append(f"{tool.name:<12} {', '.join(flags):<22} {tool.description.splitlines()[0]}")
    return "\n".join(rows)


FIX_TESTS = """Run this project's tests with run_shell and read the result.
If any test fails: find the cause in the code, fix it with edit_file, and run the tests again.
Repeat until every test passes (at most 3 rounds), then say what you changed.
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
