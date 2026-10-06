"""Fail if any relative link in the project's Markdown files points to a missing file or heading.

Run:  python scripts/check_docs.py      (exit code 1 and a list of broken links on failure)
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "node_modules", ".harness", "build", "dist"}
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")   # [text](target), not images
FENCE = re.compile(r"^(```|~~~)")


def markdown_files(root: Path):
    """The Markdown files git tracks (so folders git ignores are never checked); every *.md
    outside the usual build folders when this isn't a git checkout."""
    listed = subprocess.run(["git", "ls-files", "-z", "--", "*.md"], cwd=root, capture_output=True, text=True)
    if listed.returncode == 0 and listed.stdout:
        for name in listed.stdout.split(chr(0)):
            if name and (root / name).is_file():
                yield root / name
        return
    for path in root.rglob("*.md"):
        if not SKIP_DIRS.intersection(path.relative_to(root).parts):
            yield path


def anchors(path: Path) -> set[str]:
    """GitHub-style heading anchors: lowercase, punctuation dropped, spaces become hyphens."""
    out = set()
    for _, line in strip_code(path.read_text(encoding="utf-8")):
        if line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            out.add(re.sub(r"[^\w\- ]", "", title).replace(" ", "-"))
    return out


def strip_code(text: str) -> list[tuple[int, str]]:
    """(line number, line) for lines outside fenced code blocks: links in code are examples."""
    lines, in_code = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line.strip()):
            in_code = not in_code
        elif not in_code:
            lines.append((n, line))
    return lines


def broken_links(root: Path = ROOT) -> list[str]:
    problems = []
    for md in markdown_files(root):
        for n, line in strip_code(md.read_text(encoding="utf-8")):
            for target in LINK.findall(line):
                if re.match(r"^[a-z]+:", target):        # http:, https:, mailto:
                    continue
                file_part, _, anchor = target.partition("#")
                dest = (md.parent / file_part).resolve() if file_part else md
                where = f"{md.relative_to(root)}:{n}: {target}"
                if not dest.exists():
                    problems.append(f"{where}  (missing file)")
                elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                    problems.append(f"{where}  (missing heading)")
    return problems


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    problems = broken_links()
    for p in problems:
        print("broken link:", p)
    print(f"{len(problems)} broken link(s)" if problems else "all links OK")
    sys.exit(1 if problems else 0)
