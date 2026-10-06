"""Lesson 25: output styles: instructions added to the system prompt that change how the agent
writes, without changing what it can do.

Built in: default, concise, explanatory, learning, latex. Add your own as Markdown files in
~/.harness/styles/NAME.md or <workspace>/.harness/styles/NAME.md (frontmatter `description:`).
"""
from dataclasses import dataclass
from pathlib import Path

from harness.commands import NAME, parse_frontmatter
from harness.config import USER_DIR


@dataclass
class Style:
    name: str
    description: str
    prompt: str          # appended to the system prompt; empty for the default style
    source: str = "built-in"


BUILTIN = [
    Style("default", "the agent's normal behaviour", ""),
    Style("concise", "short answers, no preamble",
          "Be brief. Answer in at most three sentences unless the user asks for detail. "
          "Don't announce what you are about to do and don't summarise what you did unless asked; "
          "after a change, say in one line what changed."),
    Style("explanatory", "explains its choices and teaches about the codebase",
          "Explain as you work. Before a change, say in one or two sentences why it is the right change; "
          "after it, add a short 'Insight:' note about a pattern or design choice in this codebase that the "
          "user may not know. Keep explanations specific to the code at hand."),
    Style("learning", "asks you to write small, meaningful pieces of code yourself",
          "The user is learning to code. Do routine work yourself, but when a change needs a small, "
          "meaningful piece of logic (2-10 lines: a condition, a formula, a design decision), don't write it: "
          "explain what it must do and where it goes, give a hint, and ask the user to write it. "
          "Then review what they wrote."),
    Style("latex", "math typeset with LaTeX (rendered in the terminal and the web UI)",
          "Write every mathematical expression in LaTeX: inline as $...$ and displayed formulas as $$...$$ "
          "on lines of their own. Use Markdown for structure: headings, lists, tables and fenced code blocks. "
          "Never put LaTeX inside code blocks."),
]


def load_styles(workspace: Path) -> tuple[dict[str, Style], list[str]]:
    """Built-ins, then ~/.harness/styles, then <workspace>/.harness/styles. Returns (styles, warnings)."""
    styles = {s.name: s for s in BUILTIN}
    warnings = []
    for folder, source in ((USER_DIR / "styles", "user"), (workspace / ".harness" / "styles", "project")):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            name = path.stem.lower()
            if not NAME.match(name):
                warnings.append(f"{path}: style names use a-z, 0-9 and '-'; skipped")
                continue
            existing = styles.get(name)
            if source == "project" and existing is not None and existing.source == "built-in":
                warnings.append(f"{path}: a project can't replace the built-in style '{name}'; skipped")
                continue
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            if not body.strip():
                warnings.append(f"{path}: empty style; skipped")
                continue
            styles[name] = Style(name, meta.get("description", f"custom style from {path.name}"), body.strip(), source)
    return styles, warnings


def apply_style(base_prompt: str, style: Style) -> str:
    if not style.prompt:
        return base_prompt
    return f"{base_prompt}\n\n# Output style: {style.name}\n{style.prompt}"
