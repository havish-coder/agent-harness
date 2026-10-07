"""Lesson 37: assembling the system prompt from named sections.

A system prompt used to be one string with a placeholder. It now has several parts that change at
different rates, and the order is chosen for the model server's **prefix cache**: a server that has
already read the start of a prompt can skip it next time, but only up to the first character that
differs. So the parts that never change come first, then those that change when a setting does, then
those fixed for a session, and anything that changes every turn would come last.

    stability 0   the role and the rules                    never changes
    stability 1   untrusted-content rule, output style      changes when a setting or `/style` does
    stability 2   environment, workspace files, memory      fixed for a session

The prompt also has a **budget** (a share of the window). When the parts don't fit, the most volatile
trimmable part is shrunk first, and only then are optional parts dropped. What was shrunk or dropped is
recorded, so `/prompt` can say so.
"""
import datetime
import platform
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from harness.context.tokens import estimate_tokens

SEPARATOR = "\n\n"
PROMPT_SHARE = 0.25                # the system prompt may use this share of the context window
STABILITY_NAMES = {0: "never", 1: "with a setting", 2: "per session"}
MIN_TRIM = 40                      # a section is not shrunk below this many tokens: drop it instead


@dataclass
class Section:
    name: str
    text: str
    stability: int = 2                                # 0 never, 1 settings, 2 session (see the module docstring)
    required: bool = True                             # False: may be dropped when the prompt is over budget
    shrink: Callable[[int], str] | None = None        # a smaller version for a token budget (the workspace listing)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


@dataclass
class Part:
    name: str
    tokens: int
    stability: int
    note: str = ""          # "shrunk from 900", "dropped: over budget"


@dataclass
class Assembly:
    text: str
    parts: list[Part] = field(default_factory=list)
    budget: int | None = None

    @property
    def tokens(self) -> int:
        return sum(p.tokens for p in self.parts if "dropped" not in p.note)

    @property
    def over_budget(self) -> bool:
        return self.budget is not None and self.tokens > self.budget


def _smaller(section: Section, target: int) -> str | None:
    """Text from the section's `shrink` that costs fewer tokens than it does now, or None.

    `shrink` is only told roughly how many tokens to aim for (a listing turns that into a line count), so
    the first answer may be no smaller. Ask again for less, down to MIN_TRIM."""
    while target >= MIN_TRIM:
        text = section.shrink(target)
        if estimate_tokens(text) < section.tokens:
            return text
        target = int(target * 0.8)
    return None


def assemble(sections: list[Section], budget: int | None = None) -> Assembly:
    """Join the sections, most stable first, within `budget` tokens (None: no limit)."""
    ordered = sorted((s for s in sections if s.text.strip()), key=lambda s: s.stability)   # stable sort: keeps the given order
    current = [Section(s.name, s.text, s.stability, s.required, s.shrink) for s in ordered]
    notes: dict[str, str] = {}
    original = {s.name: s.tokens for s in current}

    def total() -> int:
        return sum(s.tokens for s in current) + estimate_tokens(SEPARATOR) * max(0, len(current) - 1)

    while budget is not None and total() > budget:
        over = total() - budget
        # shrink the most volatile section that can still shrink
        candidates = [s for s in current if s.shrink and s.tokens > MIN_TRIM and notes.get(s.name) != "at minimum"]
        candidates.sort(key=lambda s: -s.stability)
        if candidates:
            s = candidates[0]
            smaller = _smaller(s, max(MIN_TRIM, s.tokens - over))
            if smaller is None:                              # it can't get smaller
                notes[s.name] = "at minimum"
                continue
            s.text = smaller
            notes[s.name] = f"shrunk from {original[s.name]:,}"
            continue
        optional = [s for s in current if not s.required]
        if not optional:
            break                                             # only required parts are left; report the overshoot
        victim = max(optional, key=lambda s: (s.stability, s.tokens))
        current.remove(victim)
        notes[victim.name] = "dropped: over budget"
    parts = [Part(s.name, s.tokens, s.stability, notes.get(s.name, "")) for s in current]
    parts += [Part(name, original[name], next(x.stability for x in ordered if x.name == name), note)
              for name, note in notes.items() if note.startswith("dropped")]
    return Assembly(SEPARATOR.join(s.text for s in current), parts, budget)


# --- the environment section ----------------------------------------------------------------------

def git_summary(root: Path, timeout: float = 2.0) -> str | None:
    """`branch main, 3 changed files`, or None when this isn't a git work tree (or git isn't there)."""
    try:
        # one call: the first line names the branch (also in a repository with no commits yet), the rest are changes
        status = subprocess.run(["git", "status", "--porcelain", "--branch"], cwd=root, capture_output=True, text=True,
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = status.stdout.splitlines()
    if status.returncode != 0 or not lines or not lines[0].startswith("## "):
        return None
    head = lines[0][3:]
    if head.startswith("HEAD (no branch)"):
        branch = "detached HEAD"
    else:
        branch = head.removeprefix("No commits yet on ").removeprefix("Initial commit on ").split("...")[0]
    changed = len([line for line in lines[1:] if line.strip()])
    return f"branch {branch}, " + (f"{changed} changed file{'s' if changed != 1 else ''}" if changed else "no changes")


def environment_text(root: Path, shell_name: str, today: datetime.date | None = None, git: bool = True) -> str:
    """Facts the model can't know: today's date, the system and shell commands run in, the git state."""
    today = today or datetime.date.today()
    lines = ["# Environment", f"Date: {today.isoformat()}", f"System: {platform.system()} ({platform.machine()})",
             f"Shell for run_shell: {shell_name}"]
    summary = git_summary(root) if git else None
    if summary:
        lines.append(f"Git: {summary} (at session start)")
    return "\n".join(lines)
