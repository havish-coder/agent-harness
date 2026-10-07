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
from urllib.parse import urlsplit

from harness.security.shell import Analysis, Part, analyze, part_writes
from harness.security.taint import Taint
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
    "harness.md": "it is read as instructions in every later chat",
    "harness.local.md": "it is read as instructions in every later chat",
    "agents.md": "it is read as instructions in every later chat",
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
    notes: list[str] = field(default_factory=list)   # risks in a shell command, shown with the question (Lesson 30)


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


def match_command(pattern: str, command: str, ignore_case: bool = False) -> bool:
    """`*` matches anything, spaces included: `git status*`, `python -m pytest*`. Deny and ask rules
    ignore case (PowerShell commands and Windows file names do; matching more is the safe side)."""
    flags = re.DOTALL | (re.IGNORECASE if ignore_case else 0)
    return bool(re.fullmatch(glob_regex(pattern.strip(), None), command.strip(), flags))


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


# Lesson 30. Commands that need no rule: they only move around or print what they're given. With a
# redirection (`echo x > f`) or a path outside the workspace they are no longer "safe".
SAFE_PROGRAMS = {"cd", "pushd", "popd", "pwd", "echo", "printf", "true", "false", "sleep", "set-location",
                 "get-location", "write-output"}
# Programs that read the files named in their arguments; naming a protected folder is fine for them.
VIEWERS = {"cat", "head", "tail", "less", "more", "ls", "dir", "wc", "grep", "rg", "type", "stat", "file",
           "diff", "tree", "get-content", "get-childitem", "select-string"}


def mentions_protected(text: str) -> str | None:
    """Why a command that names this text (a path, or code containing one) always asks, or None.
    Unlike protected_reason this looks inside any word, because `python -c "open('.git/x', 'w')"`
    hides the path in a string. Over-asking is the safe direction."""
    flat = text.replace("\\", "/").casefold()
    for name, why in PROTECTED_DIRS.items():
        if re.search(rf"(?:^|[/=:'\"\s]){re.escape(name)}(?:$|[/'\"\s])", flat):
            return f"{name}/ is protected: {why} (the command mentions it)"
    for name, why in PROTECTED_FILES.items():
        if re.search(rf"(?:^|[/=:'\"\s]){re.escape(name)}(?:$|['\"\s])", flat):
            return f"{name} is protected: {why} (the command mentions it)"
    return None


GIT_CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l", "--show-origin",
                    "--show-scope", "--help", "-h"}


def git_config_risk(part: Part) -> str | None:
    """`git config key value` and `git -c key=value ...` can make git run programs (core.hooksPath,
    core.fsmonitor, core.sshCommand, aliases starting with `!`), without naming a protected path."""
    if part.program != "git" or len(part.words) < 2:
        return None
    second = part.words[1]
    if second == "-c" or (second.startswith("-c") and "=" in second):
        return "git -c sets configuration that can make git run programs"
    if second == "config" and not GIT_CONFIG_READS & set(part.words[2:]):
        return "git config can set options that make git run programs (hooks, aliases, core.fsmonitor)"
    return None


@dataclass
class Permissions:
    ws: Workspace
    mode: str = "default"
    rules: list[Rule] = field(default_factory=list)
    taint: Taint = field(default_factory=Taint)     # untrusted content read so far (Lesson 31)

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
        """allow, ask or deny for this call. After untrusted content has been read, nothing that was
        approved broadly (a mode, a rule for a whole tool) runs without asking (Lesson 31)."""
        decision = self._decide(call, tool, tainted=self.taint.active)
        if self.taint.active and decision.action == "ask" and decision.reason == CHANGES                 and self._decide(call, tool, tainted=False).action == "allow":
            decision.reason = self.taint.reason()          # it would have run, but for the taint
        return decision

    def _decide(self, call, tool, tainted: bool) -> Decision:
        try:
            subject, kind = self.subject(call, tool)
        except OutsideWorkspace as e:
            return Decision("deny", str(e))
        analysis = analyze(subject, getattr(tool, "dialect", None) or "posix") if kind == "command" and subject else None
        notes = self.notes(analysis) if kind == "command" else self.url_notes(subject) if kind == "url" else []
        read_only = tool.is_read_only(call.arguments) or (analysis is not None and self.is_safe(analysis))
        matching = [r for r in self.rules if r.action != "allow" and self.applies(r, tool.name, subject, kind, analysis)]

        def ask(reason: str, remember: Rule | None = None) -> Decision:
            return Decision("ask", reason, remember, notes)

        for rule in matching:                                                   # 1
            if rule.action == "deny":
                return Decision("deny", f"denied by the rule {rule} ({rule.source})")
        why = None                                                              # 2
        if kind == "path" and not read_only:
            why = protected_reason(subject)
        elif analysis is not None:
            why = self.command_protected(analysis)
        if why:
            return ask(why)
        for rule in matching:
            if rule.action == "ask":
                return ask(f"the rule {rule} ({rule.source}) asks first")
        if kind == "url" and tainted and subject and (urlsplit(subject).query or urlsplit(subject).fragment):
            return ask("the address carries data and this chat has read content you may not trust: "
                       "that is how a hidden instruction sends your data out")
        if self.mode == "plan" and not read_only:                               # 3
            return Decision("deny", "plan mode is on: only tools that read are allowed. "
                                    "Describe the change instead of making it")
        if self.mode == "bypass" and not tainted:
            return Decision("allow", "bypass mode")
        if self.mode == "accept-edits" and kind == "path" and not read_only and not tainted:
            return Decision("allow", "accept-edits mode")
        rule = self.allowing_rule(tool.name, subject, kind, analysis, broad=not tainted)   # 4
        if rule:
            return Decision("allow", f"allowed by the rule {rule} ({rule.source})")
        if read_only:                                                           # 5
            return Decision("allow", "reads only")
        suggestion = self.suggest(tool, subject, kind)                          # 6
        if tainted and suggestion.pattern is None:
            suggestion = None            # "always for this whole tool" would be a broad rule: not honored now
        return ask(CHANGES, suggestion)

    # --- shell commands (Lesson 30) ------------------------------------------------------------
    @staticmethod
    def url_notes(subject: str | None) -> list[str]:
        """What to tell the user about an address (Lesson 32)."""
        if not subject:
            return []
        parts = urlsplit(subject)
        notes = [f"contacts {parts.netloc}"] if parts.netloc else []
        if parts.scheme == "http":
            notes.append("not encrypted (http)")
        if parts.query or parts.fragment:
            notes.append("the address carries data after the ? (anything in it is sent to the site)")
        return notes

    @staticmethod
    def notes(analysis: Analysis | None) -> list[str]:
        if analysis is None:
            return []
        notes = list(analysis.notes)
        if not analysis.understood:
            notes.append("can't be fully checked: " + "; ".join(analysis.opaque))
        return notes

    def inside(self, word: str) -> bool:
        """Is this command-line word a path inside the workspace? `~`, `$VAR` and `-` are not."""
        if not word or word == "-" or word.startswith("~") or "$" in word or "`" in word:
            return False
        try:
            self.ws.path(word)
        except OutsideWorkspace:
            return False
        return True

    def safe_part(self, part: Part) -> bool:
        """A command that only moves around or prints: no rule needed."""
        if part.wrappers or part.program not in SAFE_PROGRAMS:
            return False
        if part.program in ("cd", "pushd", "set-location"):
            return len(part.words) == 2 and not part.dynamic[1] and self.inside(part.words[1])
        return part.program != "popd" or len(part.words) == 1

    def is_safe(self, analysis: Analysis) -> bool:
        return (analysis.understood and bool(analysis.parts) and not analysis.writes
                and all(self.safe_part(p) for p in analysis.parts))

    def command_protected(self, analysis: Analysis) -> str | None:
        """Why this command always asks: it writes to, or names, a protected place."""
        for target in analysis.writes:
            try:
                why = protected_reason(self.ws.display(self.ws.path(target)))
            except OutsideWorkspace:
                why = None
            why = why or mentions_protected(target)
            if why:
                return why
        for part in analysis.parts:
            why = git_config_risk(part)
            if why:
                return why
            if part.program in VIEWERS and not part.redirects:
                continue                                  # reading `.git/config` is fine
            for word in part.words[1:]:
                why = mentions_protected(word)
                if why:
                    return why
        return None

    def applies(self, rule: Rule, tool_name: str, subject: str | None, kind: str | None,
                analysis: Analysis | None) -> bool:
        """Does a deny or ask rule match? For commands, if it matches the whole text or any single
        command inside it, with wrappers and the program's directory removed."""
        if analysis is None or kind != "command" or rule.pattern is None or rule.exact:
            return rule.matches(tool_name, subject, kind)
        if rule.tool not in ("*", tool_name):
            return False
        texts = [subject.strip()] + [t for p in analysis.parts for t in (p.text, p.plain_text)]
        return any(match_command(rule.pattern, t, ignore_case=True) for t in texts)

    def allowing_rule(self, tool_name: str, subject: str | None, kind: str | None,
                      analysis: Analysis | None, broad: bool = True) -> Rule | None:
        """The allow rule that lets this call run, or None. A command is allowed by patterns only
        when it was fully understood and *every* command in it is covered: `pytest && curl x`
        is not allowed by `pytest*`. Commands run with a changed environment or through a wrapper
        (`env`, `sudo`, `NAME=value`) are never covered by a pattern: it isn't the command the
        user allowed."""
        allows = [r for r in self.rules if r.action == "allow" and r.tool in ("*", tool_name)]
        if not broad:                                  # after untrusted content: only what was spelled out
            allows = [r for r in allows if r.pattern is not None]
        for rule in allows:
            if rule.pattern is None or (rule.exact and subject is not None and subject.strip() == rule.pattern):
                return rule
        if analysis is None or kind != "command":
            return next((r for r in allows if r.matches(tool_name, subject, kind)), None)
        patterns = [r for r in allows if not r.exact]
        if not (analysis.understood and analysis.parts and patterns and all(self.inside(t) for t in analysis.writes)):
            return None
        used = None
        for part in analysis.parts:
            if self.safe_part(part) and not part_writes(part):
                continue
            used = None if part.wrappers else next((r for r in patterns if match_command(r.pattern, part.text)), None)
            if used is None:
                return None
        return used

    def suggest(self, tool, subject: str | None, kind: str | None) -> Rule:
        """The session rule an "always" answer adds. For commands it's this exact command, matched
        literally: allowing every command after one approval would leave the shell unguarded, and
        a `*` in an approved command (`rm *.pyc`) must not become a wildcard."""
        if kind == "command" and subject:
            return Rule("allow", tool.name, subject.strip(), "session", exact=True)
        if kind == "url" and subject:
            parts = urlsplit(subject)
            if parts.scheme and parts.netloc:                 # allow this site, not just this page
                return Rule("allow", tool.name, f"{parts.scheme}://{parts.netloc}/*", "session")
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
