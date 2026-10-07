"""Lesson 40: chats saved on disk, so a conversation survives the terminal closing.

A **project** is a workspace folder. A **chat** is one conversation in it, saved as one file of JSON lines in your user
folder (not in the workspace, so it is never committed by accident):

    <user folder>/projects/<folder name>-<hash of its path>/chats/<date>-<time>-<hex>.jsonl

The file is an **append-only log**, one JSON object a line. The conversation the model sees is not the log itself: it is what you
get by replaying it, because the harness changes the conversation as it goes (it clears old results, summarises, rolls back a
turn that failed). So besides messages the log holds the *operations*:

    {"t":"chat","v":1,"id":...,"created":...,"model":...,"parent":...}     first line
    {"t":"message","at":...,"m":{role, content, tool_calls ...}}            a message was added
    {"t":"clear","ids":[call ids]}                                          results replaced by notes (Lesson 38)
    {"t":"compact","replaced":N,"summary":{message}}                        the first N messages became this summary (39)
    {"t":"rollback","length":N}                                             a failed turn was undone: keep N messages
    {"t":"title","title":...}                                               the chat was named

Replaying the log gives back exactly the conversation as it stood, nothing is ever rewritten, and a crash can only damage the
last line, which replay skips. The system prompt is not in the log: a resumed chat gets today's.

Secrets are hidden by shape before anything is written (Lesson 34), the files are private to you where the system allows, and old
chats are removed after `chat_retention_days`.
"""
import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from harness.context.micro import is_stub, make_stub
from harness.messages import Message, message_from_dict, message_to_dict
from harness.security.redact import redacted

FORMAT = 1
TITLE_CHARS = 60
FENCE = re.compile(r'<untrusted source="([^"]*)">')
SEPARATORS = (",", ":")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30] or "project"


def project_id(root: Path | str) -> str:
    """A folder name for a project: readable, and different for two folders with the same name."""
    resolved = str(Path(root).resolve())
    key = resolved.lower() if os.name == "nt" else resolved          # Windows paths ignore case
    return f"{slug(Path(resolved).name)}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:8]}"


def scrub(value):
    """Hide secrets in every string inside a JSON-like value."""
    if isinstance(value, str):
        return redacted(value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def title_from(text: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first if len(first) <= TITLE_CHARS else first[:TITLE_CHARS - 1].rstrip() + "…"


def ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 2:
        return "just now"
    if minutes < 120:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} h ago" if hours < 48 else f"{hours // 24} d ago"


def private(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass                                   # Windows and some file systems: the user folder's own permissions apply


# --- one chat ---------------------------------------------------------------------------------

@dataclass
class ChatInfo:
    id: str
    title: str
    created: str
    updated: float            # seconds since the epoch: the file's modification time
    messages: int             # message entries in the log (before any clearing or summarising)
    model: str
    parent: str | None
    path: Path

    def age(self) -> str:
        return ago(time.time() - self.updated)


class Chat:
    """The open end of one chat file: lines are only ever added to it."""

    def __init__(self, path: Path, id: str, model: str, parent: str | None = None, title: str = ""):
        self.path, self.id, self.model, self.parent, self.title = path, id, model, parent, title

    def write(self, entry: dict) -> None:
        new = not self.path.exists()
        if new:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            private(self.path.parent, 0o700)
        with self.path.open("a", encoding="utf-8") as f:
            if new:
                header = {"t": "chat", "v": FORMAT, "id": self.id, "created": now(), "model": self.model, "parent": self.parent}
                f.write(json.dumps(header, separators=SEPARATORS) + "\n")
            f.write(json.dumps(entry, ensure_ascii=False, separators=SEPARATORS) + "\n")
        if new:
            private(self.path, 0o600)

    def message(self, m: Message) -> None:
        d = message_to_dict(m)
        d["content"] = redacted(d["content"])
        if "tool_calls" in d:
            d["tool_calls"] = [{**c, "arguments": scrub(c["arguments"])} for c in d["tool_calls"]]
        self.write({"t": "message", "at": now(), "m": d})

    def clear(self, ids: list[str]) -> None:
        self.write({"t": "clear", "ids": ids})

    def compact(self, replaced: int, summary: Message) -> None:
        self.write({"t": "compact", "replaced": replaced, "summary": message_to_dict(summary)})

    def rollback(self, length: int) -> None:
        self.write({"t": "rollback", "length": length})

    def rename(self, title: str) -> None:
        self.title = title
        self.write({"t": "title", "title": title})


# --- reading one back ------------------------------------------------------------------------

@dataclass
class Replay:
    header: dict = field(default_factory=dict)
    title: str = ""
    messages: list[Message] = field(default_factory=list)       # the conversation as it stood, without the system prompt
    archive: list[Message] = field(default_factory=list)        # what summaries replaced, oldest first
    compactions: int = 0
    untrusted: list[str] = field(default_factory=list)          # sources of fenced text found in it
    damaged: int = 0                                            # lines that couldn't be read (a crash cuts the last one)
    dropped: int = 0                                            # trailing messages removed: a tool call that never got its results


def incomplete_tail(view: list[Message]) -> int:
    """Index where an unfinished exchange starts (an assistant message whose tool calls weren't all answered), or len(view)."""
    last = max((i for i, m in enumerate(view) if m.role == "assistant" and m.tool_calls), default=None)
    if last is None:
        return len(view)
    answered = {m.tool_call_id for m in view[last + 1:] if m.role == "tool"}
    return last if any(c.id not in answered for c in view[last].tool_calls) else len(view)


def replay(path: Path) -> Replay:
    """Rebuild the conversation from a log. Unreadable lines are skipped; an unfinished exchange at the end is dropped."""
    out = Replay()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            kind = e["t"]
        except (ValueError, KeyError, TypeError):
            out.damaged += 1
            continue
        try:
            if kind == "chat":
                out.header = e
            elif kind == "title":
                out.title = e["title"]
            elif kind == "message":
                out.messages.append(message_from_dict(e["m"]))
            elif kind == "clear":
                ids = set(e["ids"])
                calls = {c.id: c for m in out.messages for c in m.tool_calls}
                for i, m in enumerate(out.messages):
                    if m.role == "tool" and m.tool_call_id in ids and not is_stub(m):
                        out.messages[i] = Message("tool", make_stub(calls.get(m.tool_call_id or ""), m),
                                                  tool_call_id=m.tool_call_id, tool_name=m.tool_name)
            elif kind == "compact":
                n = int(e["replaced"])
                out.archive.extend(out.messages[:n])
                out.messages[:n] = [message_from_dict(e["summary"])]
                out.compactions += 1
            elif kind == "rollback":
                del out.messages[int(e["length"]):]
        except (KeyError, TypeError, ValueError):
            out.damaged += 1                                    # a well-formed line that says something impossible
    keep = incomplete_tail(out.messages)
    out.dropped = len(out.messages) - keep
    del out.messages[keep:]
    for m in out.messages:
        if m.role == "tool" or (m.role == "user" and m.content.startswith("[Summary")):
            for source in FENCE.findall(m.content):
                if source not in out.untrusted:
                    out.untrusted.append(source)
    if not out.title:
        out.title = title_from(next((m.content for m in out.messages if m.role == "user"), ""))
    return out


# --- all the chats of a project --------------------------------------------------------------

def scan(path: Path) -> ChatInfo | None:
    """What the chat list shows, read without decoding every message."""
    header, title, count = None, "", 0
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith('{"t":"message"'):
                    count += 1
                elif line.startswith('{"t":"title"') or (header is None and line.startswith('{"t":"chat"')):
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("t") == "chat":
                        header = e
                    else:
                        title = e.get("title", title)
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if header is None:
        return None
    return ChatInfo(header.get("id", path.stem), title, header.get("created", ""), mtime, count, header.get("model", ""),
                    header.get("parent"), path)


class ChatStore:
    """The saved chats of one project."""

    def __init__(self, user_dir: Path, root: Path):
        self.root = Path(root).resolve()
        self.dir = Path(user_dir) / "projects" / project_id(self.root)
        self.chats_dir = self.dir / "chats"
        self.memory_dir = self.dir / "memory"        # what the agent saved for itself (Lesson 42)

    def register(self) -> None:
        """Record that this project exists (for a list of projects, Lesson 56)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "project.json").write_text(json.dumps({"path": str(self.root), "name": self.root.name, "last_used": now()}),
                                               encoding="utf-8")

    def new(self, model: str, parent: str | None = None, title: str = "") -> Chat:
        """A chat that doesn't exist on disk until something is written to it."""
        id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        return Chat(self.chats_dir / f"{id}.jsonl", id, model, parent, title)

    def infos(self) -> list[ChatInfo]:
        """Saved chats, most recently used first."""
        if not self.chats_dir.is_dir():
            return []
        found = [i for p in self.chats_dir.glob("*.jsonl") if (i := scan(p)) is not None]
        return sorted(found, key=lambda i: i.updated, reverse=True)

    def find(self, ref: str) -> ChatInfo | None:
        """A chat by its number in `infos()` (1 is the newest), by the start of its id, or by a word in its title."""
        ref = ref.strip()
        if not ref:
            return None
        infos = self.infos()
        if ref.isdigit() and 1 <= int(ref) <= len(infos):
            return infos[int(ref) - 1]
        by_id = [i for i in infos if i.id.startswith(ref)]
        if len(by_id) == 1:
            return by_id[0]
        by_title = [i for i in infos if ref.lower() in i.title.lower()]
        return by_title[0] if len(by_title) == 1 else None

    def latest(self) -> ChatInfo | None:
        infos = self.infos()
        return infos[0] if infos else None

    def open(self, info: ChatInfo) -> Chat:
        """Go on writing to a chat that already exists."""
        return Chat(info.path, info.id, info.model, info.parent, info.title)

    def fork(self, chat: Chat, model: str, title: str) -> Chat:
        """A new chat that starts as a copy of `chat`, remembering where it came from."""
        copy = self.new(model, parent=chat.id, title=title)
        lines = chat.path.read_text(encoding="utf-8", errors="replace").splitlines() if chat.path.exists() else []
        for line in lines[1:]:                                   # everything after the header; the copy has its own
            if line.startswith('{"t":"title"'):
                continue
            try:
                copy.write(json.loads(line))
            except ValueError:
                continue                                         # a damaged line stays behind
        copy.rename(title)
        return copy

    def cleanup(self, days: int, keep: set[str] = frozenset()) -> int:
        """Delete this project's chats not touched for `days` days (0: never). Returns how many."""
        if days <= 0:
            return 0
        cutoff, removed = time.time() - days * 86_400, 0
        for info in self.infos():
            if info.updated < cutoff and info.id not in keep:
                try:
                    info.path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    @staticmethod
    def projects(user_dir: Path) -> list[dict]:
        """Every project that has been used: {"path", "name", "last_used", "id"}, most recent first."""
        out = []
        for meta in (Path(user_dir) / "projects").glob("*/project.json"):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append({**data, "id": meta.parent.name})
        return sorted(out, key=lambda p: p.get("last_used", ""), reverse=True)


def recap(view: list[Message], width: int = 160) -> str:
    """The end of a conversation, in two lines, for when it is resumed."""
    def short(text: str) -> str:
        flat = " ".join(text.split())
        return flat if len(flat) <= width else flat[:width - 1] + "…"
    request = next((m.content for m in reversed(view) if m.role == "user" and not m.content.startswith("[Summary")), "")
    answer = next((m.content for m in reversed(view) if m.role == "assistant" and m.content.strip()), "")
    lines = []
    if request:
        lines.append("you:   " + short(request))
    if answer:
        lines.append("agent: " + short(answer))
    return "\n".join(lines)
