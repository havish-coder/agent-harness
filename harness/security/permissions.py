"""Lesson 29: deciding whether a tool call runs, asks, or is refused.

One function, `Permissions.decide()`, answers for every call, in a fixed order where the
strictest answer can't be overridden by a later, looser one:

    1. deny rules                      → deny   (always win, in every mode)
    2. protected paths, ask rules      → ask    (even in bypass mode, even with allow rules)
    3. the mode                        → plan: deny changes · bypass: allow · accept-edits: allow file edits
    4. allow rules                     → allow
    5. read-only tools                 → allow
    6. anything else                   → ask

Rules look like `run_shell`, `run_shell(python -m pytest*)` or `edit_file(src/**)`: a tool name,
optionally with a pattern for the tool's *subject* (the argument rules are about: a command for
run_shell, a path for file tools). They come from settings (with the layer they came from) or
from answering "always" to a question (for this session only).
"""
import os
import re
from dataclasses import dataclass, field
from typing import Literal

from harness.workspace import OutsideWorkspace, Workspace

Action = Literal["allow", "ask", "deny"]
MODES = ("default", "accept-edits", "plan", "bypass")
MODE_HELP = {
    "default": "ask before anything that changes something",
    "accept-edits": "file edits in the workspace run without asking; commands still ask",
    "plan": "read-only: tools that change things are refused",
    "bypass": "everything runs without asking, except deny rules and protected paths",
}

# Places inside the workspace where a write can make something run later. Writing there always
# asks, in every mode. Names are compared case-insensitively (Windows and macOS ignore case).
PROTECTED_DIRS = {
    ".git": "git runs hooks and settings from it",
    ".harness": "the agent's own settings, commands and styles",
    ".vscode": "the editor runs tasks and settings from it",
    ".idea": "the editor runs tasks and settings from it",
    ".husky": "it runs on every commit",
    ".github/workflows": "CI runs it, often with secrets",
}
PROTECTED_FILES = {
    ".pre-commit-config.yaml": "it runs on every commit",
    ".envrc": "direnv runs it when you enter the folder",
    ".gitattributes": "it can make git run filter programs",
}

CHANGES = "it can change things"   # the reason for an ordinary "ask"; approvers don't repeat it

RULE_HELP = "write `tool` or `tool(pattern)`, e.g. `run_shell(python -m pytest*)` or `edit_file(src/**)`"
RULE = re.compile(r"^\s*([\w.*-]+)\s*(?:\((.*)\))?\s*$", re.DOTALL)


class RuleError(ValueError):
    """A rule that can't be parsed. The message shows the expected form."""


@dataclass(frozen=True)
class Rule:
    action: Action
    tool: str                 # a tool name, or "*" for every tool
    pattern: str | None       # None: the whole tool
    source: str = "session"   # user, project, local, environment, flag, session
    exact: bool = False       # the pattern is literal text, not a glob ("always" for one command)

    @classmethod
    def parse(cls, text: str, action: Action, source: str = "session") -> "Rule":
        m = RULE.match(text)
        if not m or (m.group(2) is not None and not m.group(2).strip()):
            raise RuleError(f"can't read the rule {text!r}; {RULE_HELP}")
        return cls(action, m.group(1), m.group(2).strip() if m.group(2) else None, source)

    def __str__(self) -> str:
        return self.tool if self.pattern is None else f"{self.tool}({self.pattern})"

    def matches(self, tool_name: str, subject: str | None, kind: str | None) -> bool:
        if self.tool not in ("*", tool_name):
            return False
        if self.pattern is None:
            return True
        if subject is None:
            return False
        if self.exact:
            return subject.strip() == self.pattern
        return match_path(self.pattern, subject) if kind == "path" else match_command(self.pattern, subject)


@dataclass
class Decision:
    action: Action
    reason: str                   # shown to the user (and, for denials, to the model)
    remember: Rule | None = None  # the rule "always" would add; None when "always" can't help


def glob_regex(pattern: str, separator: str | None) -> str:
    """`*`, `?` and `**` to a regex. With a separator, `*` stays within one path part."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i) and separator:
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append(f"[^{separator}]*" if separator else ".*")
        elif c == "?":
            out.append(f"[^{separator}]" if separator else ".")
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def match_path(pattern: str, rel: str) -> bool:
    """`src` matches the folder and everything in it; `src/*.py` one level; `src/**` all levels.
    Case-insensitive on Windows, like the file system."""
    pattern = pattern.replace("\\", "/").removeprefix("./").rstrip("/")
    rel = rel.replace("\\", "/")
    flags = re.IGNORECASE if os.name == "nt" else 0
    if not any(ch in pattern for ch in "*?"):
        return bool(re.fullmatch(re.escape(pattern) + r"(?:/.*)?", rel, flags))
    return bool(re.fullmatch(glob_regex(pattern, "/"), rel, flags))


def match_command(pattern: str, command: str) -> bool:
    """`*` matches anything, spaces included: `git status*`, `python -m pytest*`."""
    return bool(re.fullmatch(glob_regex(pattern.strip(), None), command.strip(), re.DOTALL))


def protected_reason(rel: str) -> str | None:
    """Why writing to this workspace-relative path always asks, or None."""
    parts = [p.casefold() for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    for name, why in PROTECTED_DIRS.items():
        want = name.split("/")
        for i in range(len(parts) - len(want) + 1):
            if parts[i:i + len(want)] == want:
                return f"{name}/ is protected: {why}"
    if parts and parts[-1] in PROTECTED_FILES:
        return f"{parts[-1]} is protected: {PROTECTED_FILES[parts[-1]]}"
    return None


@dataclass
class Permissions:
    ws: Workspace
    mode: str = "default"
    rules: list[Rule] = field(default_factory=list)

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"unknown permission mode '{self.mode}'; choose from {', '.join(MODES)}")

    @classmethod
    def from_settings(cls, ws: Workspace, mode: str, entries: list[dict]) -> "Permissions":
        """`entries` as loaded by config: [{"action", "rule", "source"}, ...]."""
        return cls(ws, mode, [Rule.parse(e["rule"], e["action"], e["source"]) for e in entries])

    def subject(self, call, tool) -> tuple[str | None, str | None]:
        """(subject text, kind) for rule matching: kind is "path", "command" or None."""
        if not tool.subject:
            return None, None
        raw = call.arguments.get(tool.subject)
        if tool.subject == "path":
            return self.ws.display(self.ws.path(raw if raw else ".")), "path"   # may raise OutsideWorkspace
        return (str(raw) if raw is not None else None), tool.subject

    def decide(self, call, tool) -> Decision:
        try:
            subject, kind = self.subject(call, tool)
        except OutsideWorkspace as e:
            return Decision("deny", str(e))
        read_only = tool.is_read_only(call.arguments)
        matching = [r for r in self.rules if r.matches(tool.name, subject, kind)]

        for rule in matching:                                                   # 1
            if rule.action == "deny":
                return Decision("deny", f"denied by the rule {rule} ({rule.source})")
        if kind == "path" and not read_only:                                    # 2
            why = protected_reason(subject)
            if why:
                return Decision("ask", why)
        for rule in matching:
            if rule.action == "ask":
                return Decision("ask", f"the rule {rule} ({rule.source}) asks first")
        if self.mode == "plan" and not read_only:                               # 3
            return Decision("deny", "plan mode is on: only tools that read are allowed. "
                                    "Describe the change instead of making it")
        if self.mode == "bypass":
            return Decision("allow", "bypass mode")
        if self.mode == "accept-edits" and kind == "path" and not read_only:
            return Decision("allow", "accept-edits mode")
        for rule in matching:                                                   # 4
            if rule.action == "allow":
                return Decision("allow", f"allowed by the rule {rule} ({rule.source})")
        if read_only:                                                           # 5
            return Decision("allow", "reads only")
        return Decision("ask", CHANGES, self.suggest(tool, subject, kind))      # 6

    def suggest(self, tool, subject: str | None, kind: str | None) -> Rule:
        """The session rule an "always" answer adds. For commands it's this exact command, matched
        literally: allowing every command after one approval would leave the shell unguarded, and
        a `*` in an approved command (`rm *.pyc`) must not become a wildcard."""
        if kind == "command" and subject:
            return Rule("allow", tool.name, subject.strip(), "session", exact=True)
        return Rule("allow", tool.name, None, "session")

    def remember(self, rule: Rule) -> None:
        if rule not in self.rules:
            self.rules.append(rule)

    def unknown_tools(self, names: list[str]) -> list[str]:
        """Warnings for rules naming tools that don't exist (usually a typo)."""
        return [f"permission rule {rule} ({rule.source}) names an unknown tool '{rule.tool}'"
                for rule in self.rules if rule.tool != "*" and rule.tool not in names]


class AskForChanges:
    """The policy before Lesson 29, still used when an Agent gets no Permissions: reading is
    allowed, everything else asks; "always" allows that tool for the rest of the session."""

    def __init__(self):
        self.always: set[str] = set()

    def decide(self, call, tool) -> Decision:
        if tool.is_read_only(call.arguments):
            return Decision("allow", "reads only")
        if tool.name in self.always:
            return Decision("allow", f"allowed by the rule {tool.name} (session)")
        return Decision("ask", CHANGES, Rule("allow", tool.name, None, "session"))

    def remember(self, rule: Rule) -> None:
        self.always.add(rule.tool)
