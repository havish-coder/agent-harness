"""Lesson 15: providers for testing. No GPU, no network, no randomness.

- ScriptedProvider: replies you write by hand, for unit tests of the loop.
- RecordingProvider: wraps a real provider and saves every request and reply to a cassette.
- ReplayProvider: plays a cassette back, and (strict mode) fails if the agent's requests
  differ from the recorded ones, so any change in tools, prompts or the loop is caught.

A cassette is a JSON Lines file: one {"request": [...messages], "tools": [...names],
"reply": {...}} object per model call. Volatile text (the workspace path, timings) is
replaced with placeholders so cassettes work on any machine.

`committed_copy()` gives a recording or replay the workspace exactly as committed.
"""
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from harness.messages import Message, Reply, ToolCall, Usage, message_to_dict, reply_from_dict, reply_to_dict
from harness.providers.base import ProviderError


def committed_copy(repo: Path, folder: str, dest: Path) -> Path:
    """Copy `repo/folder` to `dest`, only the files git tracks. Files a user added while trying
    the agent would change the workspace snapshot in the system prompt and break replays.
    Outside a git checkout, everything is copied."""
    listed = subprocess.run(["git", "ls-files", "-z", folder], cwd=repo, capture_output=True, text=True)
    files = [f for f in listed.stdout.split("\0") if f] if listed.returncode == 0 else []
    if not files:
        shutil.copytree(repo / folder, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        return dest
    for name in files:
        target = dest / Path(name).relative_to(folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / name, target)
    return dest


class ScriptedProvider:
    """Returns pre-written replies in order and records every request it received."""

    def __init__(self, replies: list[Reply], model: str = "scripted"):
        self.model = model
        self.replies = list(replies)
        self.requests: list[tuple[list[Message], list[dict]]] = []

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply:
        self.requests.append((list(messages), tools))
        if not self.replies:
            raise ProviderError("ScriptedProvider ran out of replies")
        return self.replies.pop(0)


def text(content: str) -> Reply:
    """A scripted final answer."""
    return Reply(Message("assistant", content), "end", Usage())


def tool_calls(*calls: ToolCall) -> Reply:
    """A scripted reply asking for tools."""
    return Reply(Message("assistant", tool_calls=list(calls)), "tool_calls", Usage())


class Normalizer:
    """Replaces machine- and run-specific text with placeholders."""

    SLASHES = re.compile(r"\[(WS|HOME|PYTHON)\][^\s'\"]*")   # a placeholder path, up to whitespace/quote
    TIMINGS = [(re.compile(r"\b\d+\.\d+ ?s\b"), "[T]s"),           # 0.4 s, 0.12s
               (re.compile(r"\b\d+(\.\d+)? ms\b"), "[T]ms")]

    def __init__(self, root: Path | str | None = None):
        # Most specific first: the workspace usually sits inside the home folder.
        places = [(root, "[WS]"), (sys.base_prefix, "[PYTHON]"), (sys.prefix, "[PYTHON]"), (Path.home(), "[HOME]")]
        self.paths: list[tuple[str, str]] = []
        for place, label in places:
            if place is None:
                continue
            r = str(Path(place).resolve())
            for variant in {r, r.replace("\\", "/"), json.dumps(r)[1:-1]}:
                self.paths.append((variant, label))
        self.paths.sort(key=lambda pair: len(pair[0]), reverse=True)

    def __call__(self, s: str) -> str:
        for p, label in self.paths:
            s = s.replace(p, label)
        s = self.SLASHES.sub(lambda m: m.group(0).replace(chr(92), "/"), s)   # Windows separators → /
        for rx, placeholder in self.TIMINGS:
            s = rx.sub(placeholder, s)
        return s

    def message(self, m: Message) -> dict:
        d = message_to_dict(m)
        d["content"] = self(d["content"])
        d.pop("checkpoint", None)          # a random id for /rewind (Lesson 43): different on every run, and never sent to a model
        return d


class RecordingProvider:
    """Passes calls to a real provider and appends each request/reply pair to a cassette."""

    def __init__(self, inner, path: Path | str, root: Path | str | None = None):
        self.inner, self.model, self.path = inner, inner.model, Path(path)
        self.normalize = Normalizer(root)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")       # a new recording replaces the old one

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply:
        reply = self.inner.chat(messages, tools)
        entry = {"request": [self.normalize.message(m) for m in messages],
                 "tools": [t["name"] for t in tools],
                 "reply": reply_to_dict(reply)}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return reply


class ReplayMismatch(AssertionError):
    """The agent sent something different from what was recorded."""


class ReplayProvider:
    """Replays a cassette. In strict mode every request must match the recording."""

    def __init__(self, path: Path | str, root: Path | str | None = None, strict: bool = True):
        self.path = Path(path)
        self.entries = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]
        self.model = "replay"
        self.strict = strict
        self.normalize = Normalizer(root)
        self.calls = 0

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply:
        if self.calls >= len(self.entries):
            raise ReplayMismatch(f"the agent made more model calls than the {len(self.entries)} recorded "
                                 f"in {self.path.name}")
        entry = self.entries[self.calls]
        self.calls += 1
        if self.strict:
            got = [self.normalize.message(m) for m in messages]
            if got != entry["request"] or [t["name"] for t in tools] != entry["tools"]:
                raise ReplayMismatch(self.explain(self.calls, entry, got, [t["name"] for t in tools]))
        return reply_from_dict(entry["reply"])

    def explain(self, n: int, entry: dict, got: list[dict], tools: list[str]) -> str:
        if tools != entry["tools"]:
            return f"call {n}: tools differ: recorded {entry['tools']}, now {tools}"
        for i, (want, have) in enumerate(zip(entry["request"], got, strict=False)):
            if want != have:
                diff = difflib.unified_diff(json.dumps(want, indent=1, ensure_ascii=False).splitlines(),
                                            json.dumps(have, indent=1, ensure_ascii=False).splitlines(),
                                            "recorded", "now", lineterm="", n=1)
                return f"call {n}, message {i} ({want.get('role')}) differs:\n" + "\n".join(list(diff)[:40])
        return f"call {n}: recorded {len(entry['request'])} messages, now {len(got)}"
