"""Lesson 25b: export a chat (or its last answer) as Markdown, LaTeX or PDF.

Markdown needs nothing. LaTeX needs pandoc, PDF needs pandoc and Tectonic (a LaTeX engine
that fetches the packages it needs). Both are looked for on PATH and in ~/.harness/tools/.
Without them, export says exactly what is missing and writes what it can.
"""
import datetime
import re
import shutil
import subprocess
from pathlib import Path

from harness.config import USER_DIR
from harness.context.compact import is_summary
from harness.messages import Message
from harness.security.redact import redacted
from harness.tui.latex import tighten

ATTACHED = re.compile(r"\n\nThe user attached these with @.*", re.DOTALL)
# Characters our PDF fonts lack, written the LaTeX way instead.
MISSING_GLYPHS = {"✓": r"$\checkmark$", "✔": r"$\checkmark$", "✗": r"$\times$", "✘": r"$\times$"}
FONTS = ["-V", "mainfont=Cambria", "-V", "monofont=Consolas", "-V", "mathfont=Cambria Math"]


class ExportError(Exception):
    """Export couldn't finish. The message says why and what was written instead."""


def find_tool(name: str) -> Path | None:
    """An executable on PATH, or under ~/.harness/tools/ (e.g. tools/pandoc-3.12/pandoc.exe)."""
    found = shutil.which(name)
    if found:
        return Path(found)
    tools = USER_DIR / "tools"
    if tools.is_dir():
        for candidate in sorted(tools.rglob(f"{name}*")):
            if candidate.is_file() and candidate.stem == name and candidate.suffix in ("", ".exe"):
                return candidate
    return None


def chat_markdown(messages: list[Message], title: str, model: str, last_only: bool = False) -> str:
    """The conversation as a Markdown document: your messages, the agent's answers, and a
    one-line note for each tool it used. Tool results and attached files are left out."""
    turns = [m for m in messages if m.role in ("user", "assistant", "tool") and not is_summary(m)]   # a summary is not something anyone said
    if last_only:
        answers = [m for m in turns if m.role == "assistant" and m.content.strip()]
        turns = answers[-1:]
    date = datetime.date.today().isoformat()
    lines = ["---", f'title: "{title}"', f'subtitle: "{model}"', f'date: "{date}"', "---", ""]
    for m in turns:
        if m.role == "user":
            lines += ["## You", "", ATTACHED.sub("", m.content).strip(), ""]
        elif m.role == "assistant":
            if m.content.strip():
                lines += ["## Agent", "", tighten(m.content.strip()), ""]
            for c in m.tool_calls:
                args = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in c.arguments.items())
                lines += [f"> *used* `{c.name}({args})`", ""]
    return redacted("\n".join(lines).rstrip() + "\n")    # an exported chat leaves the machine: no secrets in it (Lesson 34)


def for_latex(markdown: str) -> str:
    out = markdown
    for char, latex in MISSING_GLYPHS.items():
        out = out.replace(char, latex)
    return out


def export(markdown: str, fmt: str, target: Path) -> Path:
    """Write `markdown` as fmt ("md", "tex" or "pdf") to target. Returns the written path."""
    target = target.with_suffix("." + fmt)
    target.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        target.write_text(markdown, encoding="utf-8")
        return target
    pandoc = find_tool("pandoc")
    if pandoc is None:
        md = target.with_suffix(".md")
        md.write_text(markdown, encoding="utf-8")
        raise ExportError(f"pandoc isn't installed, so I wrote {md.name} instead. Install pandoc "
                          "(pandoc.org) to export LaTeX and PDF")
    source = target.with_suffix(".export.md")
    source.write_text(for_latex(markdown), encoding="utf-8")
    try:
        if fmt == "tex":
            run([pandoc, source, "--standalone", "-o", target, *FONTS])
            return target
        if fmt != "pdf":
            raise ExportError(f"unknown format '{fmt}': use md, tex or pdf")
        tectonic = find_tool("tectonic")
        if tectonic is None:
            tex = target.with_suffix(".tex")
            run([pandoc, source, "--standalone", "-o", tex, *FONTS])
            raise ExportError(f"Tectonic isn't installed, so I wrote {tex.name} instead: compile it with any "
                              "LaTeX engine using XeLaTeX (or upload it to Overleaf)")
        run([pandoc, source, "-o", target, f"--pdf-engine={tectonic}", "-V", "geometry:margin=2.5cm", *FONTS],
            timeout=600)
        return target
    finally:
        source.unlink(missing_ok=True)


def run(argv, timeout: int = 120) -> None:
    done = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()[-3:]
        raise ExportError(f"{Path(str(argv[0])).stem} failed: " + " / ".join(detail))
