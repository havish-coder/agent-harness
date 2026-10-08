"""Lesson 49: skills. Instructions the agent loads when it needs them.

A project accumulates know-how that is only sometimes relevant: how to write a commit message here, how to cut a release, how to review a migration. Put all of it in the system prompt and every request
pays for all of it, and a small window has no room. Put none of it there and the agent doesn't know it exists. A **skill** is the middle: the prompt carries one line per skill (its name and what it is for), and the
full text is loaded **when the agent asks for it** (progressive disclosure), as the result of a tool call.

    <your folder>/skills/<name>/SKILL.md          a skill of yours
    <project>/.harness/skills/<name>/SKILL.md     a project's (read only in a folder you trust)

    ---
    description: Write a commit message in this project's format
    ---
    Format: `type(scope): subject`, at most 50 characters ... (the whole text, as long as it needs to be)

Next to SKILL.md a skill can have other files (an example, a checklist, a script's text); the agent reads them with `use_skill(name, file)`, which can't leave the skill's folder.

The same text is a **slash command**: `/commit-message fix the rounding bug` loads the skill and sends the request, without waiting for the agent to decide it needs it.

What a skill is not: it is not a permission. It can't allow a tool, switch a mode or approve a command; it is text, and everything the agent then does is decided as always. And it is **instructions, so it has
the standing of HARNESS.md** (Lesson 41): yours always; a project's only in a folder you trust, because a cloned repository must not get to write instructions the agent follows.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from harness.commands import NAME, parse_frontmatter
from harness.context.tokens import estimate_tokens
from harness.tools.base import Tool, tool

MAX_BODY_CHARS = 12_000
MAX_FILE_CHARS = 12_000
MAX_DESCRIPTION = 160
LISTING_TOKENS = 600                 # what the prompt spends on the list of skills
FILE_NAME = "SKILL.md"
SKIP_FOLDERS = {"__pycache__", ".git", "node_modules"}


@dataclass
class Skill:
    name: str
    description: str
    body: str
    root: Path
    source: str = "user"               # user or project
    files: list[str] = field(default_factory=list)       # other files in the folder, relative, as the agent names them
    user_only: bool = False            # only the user can start it (`/name`), the agent isn't offered it


def one_line(text: str, limit: int = MAX_DESCRIPTION) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[:limit - 1].rstrip() + "…"


def bundled_files(root: Path) -> list[str]:
    """The other files in a skill's folder (text-looking, at most 40), relative to it."""
    found = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != FILE_NAME and not (SKIP_FOLDERS & set(p.relative_to(root).parts)):
            found.append(p.relative_to(root).as_posix())
    return found[:40]


def load_skills(workspace: Path, user_dir: Path, trusted: bool) -> tuple[dict[str, Skill], list[str]]:
    """Your skills, then (in a trusted folder) the project's; a project's can't replace one of yours. Returns (skills, warnings)."""
    found: dict[str, Skill] = {}
    warnings: list[str] = []
    for folder, source in ((Path(user_dir) / "skills", "user"), (Path(workspace) / ".harness" / "skills", "project")):
        if not folder.is_dir():
            continue
        entries = sorted(p for p in folder.iterdir() if (p / FILE_NAME).is_file())
        if source == "project" and not trusted:
            if entries:
                warnings.append(f"{len(entries)} skill(s) in {folder} were not read: this folder isn't trusted (/trust if you wrote them)")
            continue
        for path in entries:
            meta, body = parse_frontmatter((path / FILE_NAME).read_text(encoding="utf-8", errors="replace"))
            name = (meta.get("name") or path.name).lower()
            if not NAME.match(name):
                warnings.append(f"{path / FILE_NAME}: skill names use a-z, 0-9 and '-'; skipped")
                continue
            if not body.strip():
                warnings.append(f"{path / FILE_NAME}: empty skill; skipped")
                continue
            if source == "project" and name in found:
                warnings.append(f"{path / FILE_NAME}: a project can't replace your skill '{name}'; skipped")
                continue
            description = meta.get("description") or next((ln for ln in body.splitlines() if ln.strip()), "")
            user_only = meta.get("user-only", meta.get("user_only", "")).lower() in ("true", "yes", "1")
            found[name] = Skill(name, one_line(description), body.strip(), path, source, bundled_files(path), user_only)
    return found, warnings


def listing_text(skills: dict[str, Skill], max_tokens: int = LISTING_TOKENS) -> str:
    """The prompt's list: one line per skill the agent may load, cut to a budget with the number left out."""
    offered = [s for s in skills.values() if not s.user_only]
    if not offered:
        return ""
    head = "Skills: instructions you can load when a task matches. Load one with use_skill(name) before you do the task.\n"
    lines, used = [], estimate_tokens(head)
    for s in offered:
        line = f"- {s.name}: {s.description}"
        if used + estimate_tokens(line) > max_tokens:
            lines.append(f"({len(offered) - len(lines)} more: /skills lists them)")
            break
        lines.append(line)
        used += estimate_tokens(line)
    return head + "\n".join(lines)


def read_bundled(skill: Skill, relative: str) -> str:
    """A file from a skill's own folder. Raises ValueError, with a message for the model, for anything else."""
    root = skill.root.resolve()
    target = (root / relative).resolve()
    if not (target == root or target.is_relative_to(root)) or not target.is_file():
        raise ValueError(f"'{relative}' isn't a file in the skill '{skill.name}'. Its files: {', '.join(skill.files) or 'none'}")
    data = target.read_bytes()
    if b"\x00" in data[:2000]:
        raise ValueError(f"'{relative}' isn't a text file")
    text = data.decode("utf-8", errors="replace")
    return text if len(text) <= MAX_FILE_CHARS else text[:MAX_FILE_CHARS] + f"\n... (cut: the file has {len(text):,} characters)"


def skill_text(skill: Skill) -> str:
    body = skill.body if len(skill.body) <= MAX_BODY_CHARS else skill.body[:MAX_BODY_CHARS] + f"\n... (cut: the skill has {len(skill.body):,} characters)"
    out = f"# Skill: {skill.name}\n{body}"
    if skill.files:
        out += f"\n\nFiles that come with this skill (read one with use_skill(name='{skill.name}', file=...)): {', '.join(skill.files)}"
    return out


def make_skill_tools(get: "callable") -> list[Tool]:
    """`use_skill(name, file)`. `get()` returns the current skills (they can be reloaded). Shown only while there is a skill to load."""

    @tool(read_only=True, concurrency_safe=True, clearable=True, enabled=lambda: any(not s.user_only for s in get().values()))
    def use_skill(name: str, file: str | None = None) -> str:
        """Load a skill's instructions (listed in your instructions), or one of the files that come with it. Do this before the task it is for.

        Args:
            name: the skill's name.
            file: a file that comes with the skill (leave out for the skill itself).
        """
        skills = get()
        found = skills.get((name or "").strip().lower())
        if found is None or found.user_only:
            available = ", ".join(s.name for s in skills.values() if not s.user_only) or "none"
            raise ValueError(f"there is no skill '{name}'. Skills: {available}")
        return read_bundled(found, file) if file else skill_text(found)

    return [use_skill]


def command_text(skill: Skill) -> str:
    """A skill as a slash command's message: its text, and where the user's own words go."""
    body = skill.body if "$ARGUMENTS" in skill.body or re.search(r"\$\d", skill.body) else skill.body + "\n\n$ARGUMENTS"
    return f"Follow this skill ({skill.name}).\n\n{body}"
