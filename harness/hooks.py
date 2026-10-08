"""Lesson 33: hooks: the user's own scripts, run at fixed points in the agent's work.

A hook is a command from settings. The harness runs it at an *event*, sends it a JSON description of what
is happening on standard input, and reads its answer:

    user_prompt_submit   before the model sees what you typed   → may block it, may add context
    pre_tool_use         before a tool call runs                → may deny, ask, or (for a routine ask) allow
    post_tool_use        after a tool call ran                  → may add context for the model (a linter's output)

Answer = exit code and standard output:
    exit 0, no output          no opinion
    exit 0, JSON object        {"decision": "allow"|"ask"|"deny", "reason": "...", "context": "..."}
    exit 2                     deny; the text on standard error is the reason
    anything else, a timeout, output that isn't JSON    the hook failed (see below)

Rules for how hooks combine with everything else (they are code the user wrote, but they are still code):

* A hook can make a decision **stricter** (deny, or ask) whatever else was decided.
* A hook's `allow` only turns a *routine* question ("it can change things") into a yes. It can't
  override a deny rule, a protected path, an ask rule, plan mode, or the pause after untrusted content.
* A hook that **fails** never allows: where the call would have run, it asks instead, and says why.
* Hooks from a project's settings run only in a folder the user has trusted (Lesson 31), because a hook
  is a program a cloned repository would otherwise get to run on your machine.
* They run with the same secret-free environment as shell commands, in the workspace folder.
"""
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from harness.security.permissions import Rule, RuleError
from harness.security.secrets import scrub_env

EVENTS = ("user_prompt_submit", "pre_tool_use", "post_tool_use")
TOOL_EVENTS = ("pre_tool_use", "post_tool_use")
DEFAULT_TIMEOUT = 10.0
MAX_TIMEOUT = 60.0
MAX_OUTPUT = 20_000        # characters read from a hook's output
DECISIONS = ("allow", "ask", "deny")
STRICTNESS = {"allow": 0, "ask": 1, "deny": 2}


class HookError(ValueError):
    """A hook entry in settings that can't be used. The message names what is wrong."""


@dataclass(frozen=True)
class Hook:
    event: str
    command: str
    match: Rule | None = None      # which tool calls (rule syntax: `run_shell(git push*)`); None = every call
    timeout: float = DEFAULT_TIMEOUT
    source: str = "user"           # the settings layer it came from

    def __str__(self) -> str:
        where = f" for {self.match}" if self.match else ""
        return f"{self.event}{where}: {self.command} ({self.source})"


@dataclass
class HookResult:
    decision: str | None = None    # allow, ask, deny, or None (no opinion)
    reason: str = ""
    context: str = ""              # text for the model
    failed: str | None = None      # why the hook couldn't answer
    hook: Hook | None = None


def check_hooks(value, where: str) -> None:
    """Validate the `hooks` setting of one layer; raises HookError (the caller names the file)."""
    if not isinstance(value, dict):
        raise HookError(f"{where}: 'hooks' must be an object like {{\"pre_tool_use\": [{{\"command\": \"...\"}}]}}")
    for event, entries in value.items():
        if event not in EVENTS:
            raise HookError(f"{where}: unknown hook event '{event}'; choose from {', '.join(EVENTS)}")
        if not isinstance(entries, list):
            raise HookError(f"{where}: hooks['{event}'] must be a list")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("command"), str) or not entry["command"].strip():
                raise HookError(f"{where}: every hook in '{event}' needs a \"command\" string")
            extra = set(entry) - {"command", "match", "timeout"}
            if extra:
                raise HookError(f"{where}: unknown key(s) {', '.join(sorted(extra))} in a '{event}' hook "
                                "(allowed: command, match, timeout)")
            timeout = entry.get("timeout", DEFAULT_TIMEOUT)
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= MAX_TIMEOUT:
                raise HookError(f"{where}: a hook's timeout must be a number of seconds, 1 to {MAX_TIMEOUT:.0f}")
            if "match" in entry:
                if event not in TOOL_EVENTS:
                    raise HookError(f"{where}: 'match' only applies to {' and '.join(TOOL_EVENTS)}")
                try:
                    Rule.parse(str(entry["match"]), "ask")
                except RuleError as e:
                    raise HookError(f"{where}: {e}") from None


def collect(layers: list[tuple[str, dict]]) -> list[Hook]:
    """Hooks from every settings layer, in order: [(source, the layer's `hooks` object), ...]."""
    hooks = []
    for source, data in layers:
        for event, entries in data.items():
            for entry in entries:
                match = Rule.parse(entry["match"], "ask", source) if entry.get("match") else None
                hooks.append(Hook(event, entry["command"].strip(), match, float(entry.get("timeout", DEFAULT_TIMEOUT)), source))
    return hooks


def from_entries(entries: list[dict]) -> list[Hook]:
    """Hooks from the loaded `hooks` setting: [{"event", "command", "match", "timeout", "source"}, ...]."""
    return [Hook(e["event"], e["command"], Rule.parse(e["match"], "ask", e["source"]) if e.get("match") else None,
                 float(e.get("timeout", DEFAULT_TIMEOUT)), e["source"]) for e in entries]


class Hooks:
    """The hooks in force, and how to run them."""

    def __init__(self, hooks: list[Hook], root: Path, permissions=None, env_keep=()):
        self.hooks = hooks
        self.root = Path(root)
        self.permissions = permissions        # used to match `match` rules the way permission rules match
        self.env_keep = tuple(env_keep)

    def __bool__(self) -> bool:
        return bool(self.hooks)

    def matching(self, event: str, call=None, tool=None) -> list[Hook]:
        found = []
        for hook in self.hooks:
            if hook.event != event:
                continue
            if hook.match is not None:
                if call is None or tool is None or not self.matches(hook.match, call, tool):
                    continue
            found.append(hook)
        return found

    def matches(self, rule: Rule, call, tool) -> bool:
        """Does this call match the hook's `match` rule? Like a deny or ask rule: for a command, any command in it."""
        if self.permissions is None:
            return rule.names(tool.name) and rule.pattern is None
        try:
            subject, kind = self.permissions.subject(call, tool)
        except Exception:
            return rule.names(tool.name) and rule.pattern is None
        from harness.security.shell import analyze
        analysis = analyze(subject, getattr(tool, "dialect", None) or "posix") if kind == "command" and subject else None
        return self.permissions.applies(rule, tool.name, subject, kind, analysis)

    def run(self, hook: Hook, payload: dict) -> HookResult:
        """Run one hook with `payload` as JSON on standard input."""
        env, _ = scrub_env(dict(os.environ), self.env_keep)
        env.update({"PYTHONUTF8": "1", "HARNESS_HOOK_EVENT": hook.event, "HARNESS_WORKSPACE": str(self.root)})
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        try:
            done = subprocess.run(hook.command, shell=True, input=json.dumps(payload), text=True, encoding="utf-8",
                                  capture_output=True, timeout=hook.timeout, cwd=self.root, env=env)
        except subprocess.TimeoutExpired:
            return HookResult(failed=f"timed out after {hook.timeout:g} s", hook=hook)
        except OSError as e:
            return HookResult(failed=f"couldn't start: {e}", hook=hook)
        out, err = done.stdout[:MAX_OUTPUT].strip(), done.stderr[:MAX_OUTPUT].strip()
        if done.returncode == 2:
            return HookResult("deny", err or "the hook refused it (exit code 2)", hook=hook)
        if done.returncode != 0:
            return HookResult(failed=f"exit code {done.returncode}" + (f": {err.splitlines()[-1]}" if err else ""), hook=hook)
        if not out:
            return HookResult(hook=hook)
        try:
            data = json.loads(out)
        except ValueError:
            return HookResult(failed="its output isn't JSON", hook=hook)
        if not isinstance(data, dict) or data.get("decision") not in (*DECISIONS, None):
            return HookResult(failed="its \"decision\" must be allow, ask or deny", hook=hook)
        return HookResult(data.get("decision"), str(data.get("reason") or ""), str(data.get("context") or "")[:MAX_OUTPUT], hook=hook)

    def combine(self, results: list[HookResult]) -> HookResult:
        """The strictest answer wins; failures are kept so the caller can refuse to allow."""
        answered = [r for r in results if r.decision]
        best = max(answered, key=lambda r: STRICTNESS[r.decision], default=HookResult())
        failures = [r for r in results if r.failed]
        merged = HookResult(best.decision, best.reason, "\n".join(r.context for r in results if r.context), hook=best.hook)
        if failures:
            merged.failed = "; ".join(f"{r.hook.command!r} {r.failed}" for r in failures)
        return merged

    def payload(self, event: str, call=None, tool=None, permissions=None, **extra) -> dict:
        data = {"event": event, "cwd": str(self.root), **extra}
        if call is not None:
            data.update({"tool": call.name, "arguments": call.arguments})
            if tool is not None and tool.subject:
                data["subject"] = call.arguments.get(tool.subject)
        permissions = permissions or self.permissions
        if permissions is not None:
            data["mode"] = permissions.mode
            data["tainted"] = permissions.taint.active
        return data

    def pre_tool(self, call, tool) -> HookResult:
        hooks = self.matching("pre_tool_use", call, tool)
        if not hooks:
            return HookResult()
        payload = self.payload("pre_tool_use", call, tool)
        return self.combine([self.run(h, payload) for h in hooks])

    def post_tool(self, call, tool, result: str) -> HookResult:
        hooks = self.matching("post_tool_use", call, tool)
        if not hooks:
            return HookResult()
        payload = self.payload("post_tool_use", call, tool, result=result[:MAX_OUTPUT])
        return self.combine([self.run(h, payload) for h in hooks])

    def user_prompt(self, text: str) -> HookResult:
        hooks = self.matching("user_prompt_submit")
        if not hooks:
            return HookResult()
        payload = self.payload("user_prompt_submit", prompt=text)
        return self.combine([self.run(h, payload) for h in hooks])
