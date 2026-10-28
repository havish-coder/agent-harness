"""Lesson 61: plugins. Someone's commands, skills, agents and styles, installed in one step and set up with your options.

    ~/.harness/plugins/NAME/plugin.json            name, version, description, options
    ~/.harness/plugins/NAME/commands/*.md          slash commands       (like ~/.harness/commands)
    ~/.harness/plugins/NAME/skills/SKILL/SKILL.md  skills               (like ~/.harness/skills)
    ~/.harness/plugins/NAME/agents/*.md            sub-agents           (like ~/.harness/agents)
    ~/.harness/plugins/NAME/styles/*.md            output styles        (like ~/.harness/styles)
    ~/.harness/plugins.json                        which are on, and the values you set

`{{option}}` anywhere in a plugin's text is replaced by your value (or the option's default), so one plugin serves a C++ project and
a Python one. **Text only**: a plugin can't run a program, add a hook or an MCP server, or change a permission. What it adds is
instructions, with the standing of your own files in ~/.harness (you installed it), and everything the agent then does goes through
the permissions as always. Plugins are installed for you, never by a project: a cloned repository can't bring one.
Where names clash, yours win: a plugin never replaces a built-in or something in ~/.harness or the project.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from harness.security.redact import redacted

MANIFEST = "plugin.json"
KINDS = ("commands", "skills", "agents", "styles")
NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
TYPES = ("string", "number", "boolean", "choice")
PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_-]*)\s*\}\}")
MAX_FILES, MAX_BYTES, MAX_VALUE = 300, 2_000_000, 200     # ponytail: a text plugin is small; these stop a mistaken folder or repo
TRUE, FALSE = {"true", "yes", "on", "1"}, {"false", "no", "off", "0"}


class PluginError(Exception):
    pass


@dataclass
class Option:
    name: str
    type: str
    default: object
    description: str = ""
    choices: list = field(default_factory=list)


@dataclass
class Plugin:
    name: str
    version: str
    description: str
    root: Path
    options: dict[str, Option]
    enabled: bool = True
    values: dict = field(default_factory=dict)          # what you set; the rest are defaults

    def value(self, key: str):
        return self.values.get(key, self.options[key].default)

    def fill(self, text: str) -> str:
        """`{{key}}` -> your value; a placeholder that isn't one of the plugin's options is left as it is."""
        def one(m):
            key = m.group(1)
            if key not in self.options:
                return m.group(0)
            v = self.value(key)
            return ("true" if v else "false") if isinstance(v, bool) else str(v)
        return PLACEHOLDER.sub(one, text)

    def contents(self) -> dict[str, list[str]]:
        """What it adds, by kind: {"commands": ["review"], "skills": [...], ...}."""
        found = {}
        for kind in KINDS:
            folder = self.root / kind
            if kind == "skills":
                names = [p.name for p in folder.iterdir() if (p / "SKILL.md").is_file()] if folder.is_dir() else []
            else:
                names = [p.stem for p in folder.glob("*.md")] if folder.is_dir() else []
            if names:
                found[kind] = sorted(names)
        return found


def home(user_dir: Path) -> Path:
    return Path(user_dir) / "plugins"


def read_state(user_dir: Path) -> dict:
    try:
        data = json.loads((Path(user_dir) / "plugins.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(user_dir: Path, state: dict) -> None:
    Path(user_dir).mkdir(parents=True, exist_ok=True)
    (Path(user_dir) / "plugins.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_option(o: Option, raw) -> object:
    """A value for option `o` from text (a command) or JSON (the manifest's default): the declared type, or PluginError."""
    text = str(raw).strip()
    if o.type == "boolean":
        if isinstance(raw, bool) or text.lower() in TRUE | FALSE:
            return raw if isinstance(raw, bool) else text.lower() in TRUE
        raise PluginError(f"'{o.name}' is true or false")
    if o.type == "number":
        try:
            n = float(text)
        except ValueError:
            raise PluginError(f"'{o.name}' is a number") from None
        return int(n) if n.is_integer() else n
    if o.type == "choice":
        if text not in o.choices:
            raise PluginError(f"'{o.name}' is one of: {', '.join(map(str, o.choices))}")
        return text
    if len(text) > MAX_VALUE or "\n" in text:
        raise PluginError(f"'{o.name}' is one line of at most {MAX_VALUE} characters")
    return text


def read_manifest(root: Path) -> Plugin:
    try:
        data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except OSError:
        raise PluginError(f"no {MANIFEST} in {root}") from None
    except ValueError as e:
        raise PluginError(f"{MANIFEST} isn't valid JSON: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("options") or {}, dict):
        raise PluginError(f"{MANIFEST} must be a JSON object, and its 'options' an object of name: {{type, ...}}")
    name = str(data.get("name", ""))
    if not NAME.match(name):
        raise PluginError(f"{MANIFEST}: 'name' must be a-z, 0-9 and '-', starting with a letter (got {name!r})")
    options = {}
    for key, spec in (data.get("options") or {}).items():
        if not PLACEHOLDER.fullmatch("{{" + str(key) + "}}") or not isinstance(spec, dict) or spec.get("type") not in TYPES:
            raise PluginError(f"{MANIFEST}: option {key!r} needs a name of a-z, 0-9, '-' and '_', and a type: {', '.join(TYPES)}")
        if not isinstance(spec.get("choices") or [], list):
            raise PluginError(f"{MANIFEST}: option {key!r} has 'choices' that isn't a list")
        o = Option(key, spec["type"], None, str(spec.get("description", "")), [str(c) for c in spec.get("choices") or []])
        if o.type == "choice" and not o.choices:
            raise PluginError(f"{MANIFEST}: option {key!r} is a choice with no 'choices'")
        o.default = check_option(o, spec.get("default", o.choices[0] if o.choices else False if o.type == "boolean" else 0 if o.type == "number" else ""))
        options[key] = o
    plugin = Plugin(name, str(data.get("version", "0.0.0")), " ".join(str(data.get("description", "")).split())[:200], root, options)
    if not plugin.contents():
        raise PluginError(f"{name} adds nothing: it needs commands/, skills/, agents/ or styles/")
    return plugin


def mine(state: dict, name: str) -> dict:
    """A plugin's entry in plugins.json, made an object with an object of options if a hand edit left something else there."""
    entry = state.get(name)
    entry = state[name] = entry if isinstance(entry, dict) else {}
    if not isinstance(entry.get("options", {}), dict):
        entry["options"] = {}
    return entry


def installed(user_dir: Path) -> tuple[list[Plugin], list[str]]:
    """Every installed plugin with your state, and warnings for folders that aren't valid plugins."""
    plugins, warnings, state = [], [], read_state(user_dir)
    folder = home(user_dir)
    # ponytail: dot folders are install's staging copies (.NAME.new, .NAME.old), never plugins
    for root in sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")) if folder.is_dir() else []:
        try:
            p = read_manifest(root)
        except PluginError as e:
            warnings.append(f"plugin {root.name}: {e}; skipped")
            continue
        entry = mine(state, p.name)
        p.enabled = entry.get("enabled", True) is not False
        for key, raw in entry.get("options", {}).items():
            if key in p.options:
                try:
                    p.values[key] = check_option(p.options[key], raw)
                except PluginError as e:
                    warnings.append(f"plugin {p.name}: {e}; using the default")
        plugins.append(p)
    return plugins, warnings


def folders(user_dir: Path, kind: str) -> list[tuple[Path, str, callable]]:
    """For a loader: (folder, source, fill) for each enabled plugin that has `kind`."""
    return [(p.root / kind, f"plugin {p.name}", p.fill) for p in installed(user_dir)[0] if p.enabled and (p.root / kind).is_dir()]


def is_git(source: str) -> bool:
    return source.startswith(("https://", "http://", "git@", "ssh://")) or source.endswith(".git")


def check_tree(root: Path) -> None:
    """No links (a link could copy a file from elsewhere on this computer into a skill the agent reads), and small."""
    files = size = 0
    for p in root.rglob("*"):
        if ".git" in p.relative_to(root).parts:
            continue
        if p.is_symlink():
            raise PluginError(f"{p.relative_to(root)} is a link: plugins are plain files")
        if p.is_file():
            files, size = files + 1, size + p.stat().st_size
    if files > MAX_FILES or size > MAX_BYTES:
        raise PluginError(f"too big for a text plugin ({files} files, {size:,} bytes; at most {MAX_FILES} and {MAX_BYTES:,})")


def delete(path: Path) -> None:
    """shutil.rmtree that also deletes read-only files: Windows refuses them, and copytree keeps a source folder's read-only bit."""
    def again(func, p, _):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, **({"onexc": again} if sys.version_info >= (3, 12) else {"onerror": again}))


def place(root: Path, dest: Path) -> None:
    """Copy `root` to `dest`, replacing what's there only once the copy is whole: a failure leaves the old version in place."""
    new, old = dest.with_name(f".{dest.name}.new"), dest.with_name(f".{dest.name}.old")
    try:
        for leftover in (new, old):                     # from an install that was cut off
            if leftover.exists():
                delete(leftover)
        shutil.copytree(root, new, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        if dest.exists():
            dest.rename(old)
        try:
            new.rename(dest)
        except OSError:
            if old.exists():
                old.rename(dest)
            raise
    except (OSError, shutil.Error) as e:
        shutil.rmtree(new, ignore_errors=True)
        raise PluginError(f"couldn't copy the plugin into {dest}: {e}") from None
    shutil.rmtree(old, ignore_errors=True)              # ponytail: a leftover .old is hidden from installed() and cleared next time


def install(source: str, user_dir: Path, force: bool = False) -> Plugin:
    """Copy a plugin folder, or clone a git repository (`git clone --depth 1`, without its .git), into ~/.harness/plugins/NAME."""
    with tempfile.TemporaryDirectory() as tmp:
        if is_git(source):
            root = Path(tmp) / "src"
            # No prompts: a private or mistyped address fails at once instead of asking for a password nobody can type here.
            quiet = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
            try:
                done = subprocess.run(["git", "clone", "--depth", "1", "--", source, str(root)], capture_output=True, text=True,
                                      timeout=120, stdin=subprocess.DEVNULL, env=quiet)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise PluginError(f"git clone failed: {e}") from None
            if done.returncode != 0:
                raise PluginError("git clone failed: " + (done.stderr.strip().splitlines() or ["no output"])[-1])
        else:
            root = Path(source).expanduser()
            if not root.is_dir():
                raise PluginError(f"{source} is neither a folder nor a git address")
            if root.resolve().is_relative_to(home(user_dir).resolve()):
                raise PluginError(f"{source} is already in {home(user_dir)}: install from the plugin's own folder or git address")
        plugin = read_manifest(root)
        check_tree(root)
        dest = home(user_dir) / plugin.name
        if dest.exists() and not force:
            raise PluginError(f"{plugin.name} is already installed: /plugin install --force {source} replaces it (your options are kept)")
        place(root, dest)
    state = read_state(user_dir)
    state[plugin.name] = {"enabled": True, "options": mine(state, plugin.name).get("options", {})}
    write_state(user_dir, state)
    return read_manifest(dest)


def find(name: str, user_dir: Path) -> Plugin:
    for p in installed(user_dir)[0]:
        if p.name == name:
            return p
    raise PluginError(f"no plugin called '{name}' (/plugin lists them)")


def remove(name: str, user_dir: Path) -> None:
    root = find(name, user_dir).root
    try:
        delete(root)
    except OSError as e:
        raise PluginError(f"couldn't delete {root}: {e}. Close anything using it and run /plugin remove {name} again") from None
    state = read_state(user_dir)
    state.pop(name, None)
    write_state(user_dir, state)


def set_enabled(name: str, user_dir: Path, on: bool) -> None:
    find(name, user_dir)
    state = read_state(user_dir)
    mine(state, name)["enabled"] = on
    write_state(user_dir, state)


def set_option(name: str, key: str, raw: str, user_dir: Path) -> object:
    plugin = find(name, user_dir)
    if key not in plugin.options:
        raise PluginError(f"{name} has no option '{key}' (it has: {', '.join(plugin.options) or 'none'})")
    if redacted(raw) != raw:
        raise PluginError("that looks like a secret. Option values are kept in plain text and become part of what the model reads: "
                          "keep keys in environment variables")
    value = check_option(plugin.options[key], raw)
    state = read_state(user_dir)
    mine(state, name).setdefault("options", {})[key] = value
    write_state(user_dir, state)
    return value


def as_json(user_dir: Path) -> list[dict]:
    """For the web page's Settings."""
    return [{"name": p.name, "version": p.version, "description": p.description, "enabled": p.enabled, "adds": p.contents(),
             "options": [{"key": o.name, "type": o.type, "value": p.value(o.name), "default": o.default, "choices": o.choices,
                          "description": o.description} for o in p.options.values()]}
            for p in installed(user_dir)[0]]
