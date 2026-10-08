"""Lesson 34: finding secrets in text and replacing them.

Used before text leaves the machine or is kept: tool results on their way to the model (a `.env` file
read by `read_file`), the audit log, exported chats. It looks for the *shapes* secrets have, so it can
miss a secret with no recognisable shape and it can hide something that only looks like one; both are
trade-offs we state in the lesson. It never needs to know the secret in advance.

Every replacement keeps enough to see what was there and why it went: `[REDACTED: api key]`.
"""
import re
from dataclasses import dataclass

from harness.security.secrets import secret_name

PLACEHOLDER = "[REDACTED: {}]"

# (kind, pattern). The whole match is replaced, except where a pattern has a group named `secret`:
# then only that part is (so `Authorization: Bearer <token>` keeps its label).
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL)),
    ("api key", re.compile(r"\b(?:sk-ant-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{16,}|AIza[A-Za-z0-9_-]{30,})")),
    ("github token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("aws access key", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("stripe key", re.compile(r"\b[rsp]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("jwt", re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),   # not from inside a run: see ASSIGNMENT
    ("bearer token", re.compile(r"(?i)\b(?:authorization:\s*)?bearer\s+(?P<secret>[A-Za-z0-9._~+/=-]{20,})")),
    ("url password", re.compile(r"(?i)\b[a-z][a-z0-9+.-]{0,30}://[^\s/:@]+:(?P<secret>[^\s/@]+)@")),     # a scheme is short: see ASSIGNMENT
]
# NAME=value or NAME: value, where NAME says it is secret (ANTHROPIC_API_KEY=..., "db_password": "...").
# A name starts where a word starts and is at most 100 characters: unbounded, a long word with no "=" after it was tried
# from every letter, to its end and back (200 KB of base64 took minutes; found by the web UI's file viewer, Lesson 54).
ASSIGNMENT = re.compile(r"""(?<![A-Za-z0-9_])(?P<name>["']?[A-Za-z_][A-Za-z0-9_.-]{0,100}["']?)(?P<sep>\s*[=:]\s*)(?P<quote>["']?)(?P<secret>[^\s"',;#]{6,})(?P=quote)""")
# A value that points at a secret instead of being one: `$KEY`, `os.environ[...]`, `getenv(...)`, `<your key>`, `xxxxxxxx`.
REFERENCE = re.compile(r"^[$<{%]|^(?:os|process|env|self|config|settings)\.|getenv|environ|[(\[]|^your|^[x*.-]+$", re.IGNORECASE)
MIN_SECRET_LENGTH = 8      # shorter values after a secret-looking name (`TOKEN=1`) are settings, not secrets


@dataclass
class Redaction:
    text: str
    found: list[str]          # the kinds that were replaced, in order, with repeats

    @property
    def count(self) -> int:
        return len(self.found)


def redact(text: str) -> Redaction:
    """`text` with secrets replaced, and what was replaced."""
    found: list[str] = []

    def replace(kind: str, match: re.Match) -> str:
        found.append(kind)
        if "secret" in match.re.groupindex and match.group("secret") is not None:
            whole, start = match.group(0), match.start()
            a, b = match.start("secret") - start, match.end("secret") - start
            return whole[:a] + PLACEHOLDER.format(kind) + whole[b:]
        return PLACEHOLDER.format(kind)

    for kind, pattern in PATTERNS:
        text = pattern.sub(lambda m, k=kind: replace(k, m), text)

    def assignment(match: re.Match) -> str:
        name = match.group("name").strip("\"'")
        value = match.group("secret")
        if value.startswith("[REDACTED") or len(value) < MIN_SECRET_LENGTH or not secret_name(name) or REFERENCE.search(value):
            return match.group(0)
        found.append("secret value")
        return f'{match.group("name")}{match.group("sep")}{match.group("quote")}{PLACEHOLDER.format("secret value")}{match.group("quote")}'

    text = ASSIGNMENT.sub(assignment, text)
    return Redaction(text, found)


def redacted(text: str) -> str:
    return redact(text).text
