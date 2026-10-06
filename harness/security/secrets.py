"""Lesson 30: telling secrets from ordinary values.

Used now to keep secret environment variables away from shell commands, and in Lesson 34 to
redact secrets from logs, exports and tool output. Two signals, either is enough:

- the **name** says so: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `DB_PASSWORD`, `AWS_SECRET_ACCESS_KEY`,
  `sessionCookie`: a word in it is KEY, TOKEN, SECRET, PASSWORD ... (so `KEYBOARD` or `PATH` are not);
- the **value** looks like a key: `sk-...`, `sk-ant-...`, `gsk_...`, `AIza...`.
"""
import re

SECRET_VALUES = re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{16,}|AIza[A-Za-z0-9_-]{30,})")

SECRET_WORDS = {"KEY", "KEYS", "TOKEN", "TOKENS", "SECRET", "SECRETS", "PASSWORD", "PASSWD", "PASS", "AUTH",
                "COOKIE", "COOKIES", "CREDENTIAL", "CREDENTIALS", "PAT", "DSN", "APIKEY", "AUTHORIZATION"}
SECRET_ENDINGS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIALS")
# Words glued together (APIKEY, GITHUBTOKEN): the ending counts only after a prefix that says what it is for,
# so MONKEY and TURKEY aren't secrets.
GLUED_PREFIXES = {"API", "ACCESS", "SECRET", "PRIVATE", "AUTH", "GITHUB", "GITLAB", "SLACK", "BOT", "SESSION", "REFRESH",
                  "BEARER", "CLIENT", "DB", "APP", "SIGNING", "MASTER", "ENCRYPTION", "OPENAI", "ANTHROPIC", "STRIPE"}


def words(name: str) -> list[str]:
    """`AWS_SECRET_ACCESS_KEY` → AWS SECRET ACCESS KEY; `sessionCookie` → SESSION COOKIE."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return [w.upper() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]


def secret_name(name: str) -> bool:
    parts = words(name)
    if any(p in SECRET_WORDS for p in parts):
        return True
    last = parts[-1] if parts else ""
    return any(last.endswith(end) and last[:-len(end)] in GLUED_PREFIXES for end in SECRET_ENDINGS)


def secret_value(value: str) -> bool:
    return bool(SECRET_VALUES.search(value))


def scrub_env(env: dict[str, str], keep=()) -> tuple[dict[str, str], list[str]]:
    """(env without secrets, names removed). `keep` lists names to leave in, whatever they look like.
    Names are compared without case, as Windows does."""
    kept = {k.upper() for k in keep}
    clean, removed = {}, []
    for name, value in env.items():
        if name.upper() not in kept and (secret_name(name) or secret_value(value)):
            removed.append(name)
        else:
            clean[name] = value
    return clean, removed
