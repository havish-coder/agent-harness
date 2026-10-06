"""Lesson 20: layered settings, and secrets kept out of them.

Settings come from several places. Later layers override earlier ones:

    defaults < user (~/.harness/settings.json) < project (<workspace>/.harness/settings.json)
             < local (<workspace>/.harness/settings.local.json) < environment (HARNESS_*) < flags

- user: your preferences on this machine, for every project
- project: shared with everyone who works on the project (commit it)
- local: your personal overrides for this project (never commit it)

Secrets (API keys) never go in settings files. They come from environment variables, which may
be loaded from a `.env` file (`~/.harness/.env`, then `<workspace>/.env`) that is never committed.
"""
import difflib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field, fields
from pathlib import Path

USER_DIR = Path(os.environ.get("HARNESS_HOME", Path.home() / ".harness"))
SECRET_KEY_NAMES = re.compile(r"(api[_-]?key|secret|token|password)", re.IGNORECASE)
SECRET_VALUES = re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{16,}|AIza[A-Za-z0-9_-]{30,})")


class ConfigError(Exception):
    """A settings file is invalid. The message names the file and the key."""


@dataclass
class Settings:
    provider: str = "ollama"
    model: str | None = None
    base_url: str | None = None
    fallback_model: str | None = None
    temperature: float | None = None
    context_window: int = 8192          # Ollama's num_ctx
    max_steps: int = 20
    stream: bool = True
    think: bool = False
    shell: str | None = None            # bash, pwsh or powershell (see run_shell)
    max_retries: int = 4
    prices: dict = field(default_factory=dict)   # model prefix → {"input", "output", ...} $/M tokens
    output_style: str = "default"                # see harness/styles.py (Lesson 25)
    status_line: str | None = None               # a shell command whose output is the status line
    sources: dict = field(default_factory=dict, repr=False, compare=False)   # key → where it came from


SETTING_NAMES = [f.name for f in fields(Settings) if f.name != "sources"]
# Settings that decide where your prompts (and code) are sent. A project file setting them is
# worth a warning: a cloned repository could point the agent at someone else's server.
SENSITIVE = {"provider", "base_url"}


def layer_files(workspace: Path) -> list[tuple[str, Path]]:
    return [("user", USER_DIR / "settings.json"),
            ("project", workspace / ".harness" / "settings.json"),
            ("local", workspace / ".harness" / "settings.local.json")]


# What each setting accepts. (Spelled out rather than read from the annotations: clearer, and
# the same on every Python version.)
TYPES: dict[str, tuple] = {
    "provider": (str,), "model": (str, type(None)), "base_url": (str, type(None)),
    "fallback_model": (str, type(None)), "temperature": (int, float, type(None)),
    "context_window": (int,), "max_steps": (int,), "stream": (bool,), "think": (bool,),
    "shell": (str, type(None)), "max_retries": (int,), "prices": (dict,),
    "output_style": (str,), "status_line": (str, type(None)),
}
# Settings that run a program. A project file may not set them: a cloned repository would run
# its own code on your machine just by being opened.
RUNS_CODE = {"status_line"}


def _type_ok(name: str, value) -> bool:
    kinds = TYPES[name]
    if isinstance(value, bool) and bool not in kinds:     # True is an int in Python, not in JSON
        return False
    return isinstance(value, kinds)


def check_layer(data: dict, where: str) -> list[str]:
    """Validate one layer; returns warnings, raises ConfigError for real errors."""
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: settings must be a JSON object")
    warnings = []
    for key, value in data.items():
        if key not in SETTING_NAMES:
            if SECRET_KEY_NAMES.search(key):
                raise ConfigError(f"{where}: '{key}' looks like a secret. Secrets don't belong in settings "
                                  "files; put them in an environment variable or a .env file")
            close = difflib.get_close_matches(key, SETTING_NAMES, n=1)
            warnings.append(f"{where}: unknown setting '{key}'" + (f" (did you mean '{close[0]}'?)" if close else ""))
            continue
        if not _type_ok(key, value):
            raise ConfigError(f"{where}: '{key}' has the wrong type ({type(value).__name__})")
        if key == "prices":
            check_prices(value, where)
        if isinstance(value, str) and SECRET_VALUES.search(value):
            raise ConfigError(f"{where}: '{key}' contains what looks like an API key. Use an environment variable")
    return warnings


def check_prices(prices: dict, where: str) -> None:
    for model, p in prices.items():
        fields_ok = isinstance(p, dict) and {"input", "output"} <= p.keys() <= {"input", "output", "cache_read", "cache_write"}
        if not fields_ok or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p.values()):
            raise ConfigError(f"{where}: prices['{model}'] must look like "
                              '{"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5} (dollars per million tokens)')


def read_layer(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: invalid JSON at line {e.lineno}: {e.msg}") from None


def env_layer(environ) -> dict:
    """HARNESS_MODEL=... → {"model": ...}, converted to the setting's type."""
    out = {}
    for name in SETTING_NAMES:
        raw = environ.get(f"HARNESS_{name.upper()}")
        if raw is None:
            continue
        kinds = TYPES[name]
        try:
            if bool in kinds:
                out[name] = raw.strip().lower() in ("1", "true", "yes", "on")
            elif float in kinds:
                out[name] = float(raw)
            elif int in kinds:
                out[name] = int(raw)
            else:
                out[name] = raw
        except ValueError:
            raise ConfigError(f"environment: HARNESS_{name.upper()}={raw!r} is not a number") from None
    return out


def load_settings(workspace: Path, flags: dict | None = None, environ=None) -> tuple[Settings, list[str]]:
    """Merge every layer. Returns the settings (with .sources) and a list of warnings."""
    environ = os.environ if environ is None else environ
    settings, warnings = Settings(), []
    settings.sources = {name: "default" for name in SETTING_NAMES}
    layers = [(label, read_layer(path)) for label, path in layer_files(workspace) if path.is_file()]
    layers += [("environment", env_layer(environ)), ("flag", {k: v for k, v in (flags or {}).items() if v is not None})]
    for label, data in layers:
        warnings += check_layer(data, label)
        if label == "project" and RUNS_CODE & data.keys():
            for key in sorted(RUNS_CODE & data.keys()):
                warnings.append(f"project settings can't set '{key}' (it runs a program); ignored. "
                                "Put it in your user or local settings")
            data = {k: v for k, v in data.items() if k not in RUNS_CODE}
        if label == "project" and SENSITIVE & data.keys():
            warnings.append("project settings choose where your prompts are sent: "
                            + ", ".join(f"{k}={data[k]!r}" for k in sorted(SENSITIVE & data.keys())))
        for key, value in data.items():
            if key in SETTING_NAMES:
                if key == "prices":                      # price tables add up across layers
                    value = {**settings.prices, **value}
                setattr(settings, key, value)
                settings.sources[key] = label
    return settings, warnings


# --- secrets: .env files ---

def parse_dotenv(text: str) -> dict[str, str]:
    """KEY=value lines; `export`, quotes and # comments allowed. No variable expansion."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        out[key.strip()] = value
    return out


def load_dotenv(workspace: Path, environ=None) -> tuple[list[str], list[str]]:
    """Load ~/.harness/.env and <workspace>/.env into the environment, never overriding what's
    already set. Returns (names loaded, warnings)."""
    environ = os.environ if environ is None else environ
    loaded, warnings = [], []
    for path in (USER_DIR / ".env", workspace / ".env"):
        if not path.is_file():
            continue
        if path.parent == workspace and not ignored_by_git(workspace, path):
            warnings.append(f"{path.name} in the workspace is not ignored by git: it could be committed "
                            "with your keys in it. Add '.env' to .gitignore")
        for key, value in parse_dotenv(path.read_text(encoding="utf-8")).items():
            if key not in environ:
                environ[key] = value
                loaded.append(key)
    return loaded, warnings


def ignored_by_git(repo: Path, path: Path) -> bool:
    """True if git ignores `path`, or if this isn't a git repository (nothing to commit it to)."""
    try:
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo,
                                capture_output=True, text=True, timeout=10)
        if inside.returncode != 0:
            return True
        return subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=repo,
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return True


def describe(settings: Settings) -> str:
    """Effective settings and where each came from, for --show-config."""
    width = max(map(len, SETTING_NAMES))
    return "\n".join(f"{name:<{width}}  {getattr(settings, name)!r:<28} ({settings.sources.get(name, 'default')})"
                     for name in SETTING_NAMES)
