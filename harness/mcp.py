"""Lesson 51: MCP, tools that live in other programs.

The Model Context Protocol lets any program offer tools to any agent. A *server* is a program the harness starts; the two talk JSON-RPC 2.0 over the
server's stdin and stdout, one JSON message per line (the "stdio" transport). Four messages are enough for tools:

    harness -> server   initialize {protocolVersion, capabilities, clientInfo}     the server answers with its version and what it offers
    harness -> server   notifications/initialized                                  (a notification: no id, no answer)
    harness -> server   tools/list {cursor?}                                       -> {tools: [{name, description, inputSchema}], nextCursor?}
    harness -> server   tools/call {name, arguments}                               -> {content: [{type: "text", text}, ...], isError?}

The server may ask things of the harness too. We offer it nothing (no sampling, no roots), so the only request it may send is `ping`, answered with
{}; anything else gets "method not found". Its notifications (logs, progress, "my tools changed") are ignored.

Each tool of a server becomes an ordinary `Tool` named `mcp__<server>__<tool>`: it goes through the same registry, permission rules, hooks,
audit log and tool search as the built-in ones. Three choices make it safe by default:

  * a server comes only from your user settings (~/.harness/settings.json), never from a project folder: it is a program, and it runs as you;
  * every MCP tool counts as one that changes things, so it asks before it runs. A server may *say* a tool only reads (`readOnlyHint`); the
    protocol calls that a hint, and a hint written by someone else must not decide what runs without asking;
  * what a tool returns was written by another program, so it is untrusted content (Lesson 31): fenced, and it taints the chat. A server whose
    output is yours can be marked `"trusted": true`.
"""
import itertools
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from harness import __version__
from harness.tools.base import Tool
from harness.tools.shell import child_env, kill_tree

PROTOCOL = "2025-06-18"
SUPPORTED = {"2025-06-18", "2025-03-26", "2024-11-05"}   # the stdio transport and the tool messages are the same in all three
START_TIMEOUT = 30           # seconds for a server to start and list its tools (`npx` may download the package first)
CALL_TIMEOUT = 120           # ponytail: one limit for every call; add a per-server "timeout" setting when a server needs longer
MAX_DESCRIPTION = 1024       # characters of a tool's description the model is shown: a server could otherwise fill the window
MAX_PAGES = 50               # tools/list pages: a server that keeps answering with a cursor must not hang the start
LOG_LIMIT = 1_000_000        # a server's log is started afresh when it is bigger than this
SERVER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,30}$")
SERVER_KEYS = {"command", "args", "env", "trusted"}
UNSAFE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x08\x0b-\x1f\x7f]")   # terminal escape codes, then control characters (newline and tab stay)


class MCPError(Exception):
    """The server didn't start, stopped, or didn't answer. The message is the harness's own words."""


class ServerError(MCPError):
    """The server answered with a JSON-RPC error. The message was written by the server."""


def check_servers(servers: dict, where: str) -> list[str]:
    """Problems with an `mcp_servers` setting, as messages (empty: fine)."""
    problems = []
    for name, spec in servers.items():
        if not SERVER_NAME.match(name) or "__" in name:
            problems.append(f"{where}: MCP server name '{name}' must be 1-30 letters, digits, '-' or '_' (no '__')")
        elif not isinstance(spec, dict) or not isinstance(spec.get("command"), str) or not spec["command"].strip():
            problems.append(f"{where}: mcp_servers['{name}'] needs a \"command\", e.g. {{\"command\": \"npx\", \"args\": [\"-y\", \"some-server\"]}}")
        elif set(spec) - SERVER_KEYS:
            problems.append(f"{where}: mcp_servers['{name}'] has unknown key(s) {', '.join(sorted(set(spec) - SERVER_KEYS))}; "
                            f"use {', '.join(sorted(SERVER_KEYS))}")
        elif not all(isinstance(spec.get(k, []), list) and all(isinstance(x, str) for x in spec.get(k, [])) for k in ("args", "env")):
            problems.append(f"{where}: mcp_servers['{name}']: \"args\" and \"env\" must be lists of strings (env: names of variables to pass on)")
        elif not isinstance(spec.get("trusted", False), bool):
            problems.append(f"{where}: mcp_servers['{name}']: \"trusted\" must be true or false")
    return problems


class Server:
    """One running MCP server. `request` may be called from any thread; a reader thread hands each answer to the request waiting for it."""

    def __init__(self, name: str, command: str, args=(), env_keep=(), cwd: Path | None = None, log: Path | None = None,
                 trusted: bool = False):
        self.name, self.trusted, self.log = name, trusted, log
        self.tools: list[dict] = []
        self.info: dict = {}                          # what the server said about itself in initialize
        self.pending: dict[int, queue.Queue] = {}
        self.ids = itertools.count(1)
        self.write_lock = threading.Lock()
        self.closed = False
        exe = shutil.which(command) or command        # Windows: `npx` is npx.cmd, which only a full path finds
        err = subprocess.DEVNULL
        if log is not None:
            log.parent.mkdir(parents=True, exist_ok=True)
            err = open(log, "ab" if log.exists() and log.stat().st_size < LOG_LIMIT else "wb")   # noqa: SIM115 (the child keeps it)
            err.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {command} {' '.join(args)}\n".encode())
            err.flush()
        # its own process group, as for commands: Ctrl+C in the terminal stops the agent, not the servers, and kill_tree can stop all it started
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        try:
            self.proc = subprocess.Popen([exe, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, cwd=cwd,
                                         env=child_env(env_keep), **group)
        except OSError as e:
            raise MCPError(f"can't start {command!r}: {e.strerror or e}") from None
        finally:
            if err is not subprocess.DEVNULL:
                err.close()                           # the server has its own handle now
        threading.Thread(target=self._read, name=f"mcp-{name}", daemon=True).start()

    # --- the wire -----------------------------------------------------------------------------
    def _send(self, message: dict) -> None:
        data = (json.dumps(message) + "\n").encode("utf-8")
        with self.write_lock:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def _read(self) -> None:
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue                              # a server must log to stderr; a stray line on stdout is skipped
            if not isinstance(message, dict):
                continue                              # batches were removed from the protocol in 2025-06-18
            if "method" in message:                   # the server asks or tells us something
                if "id" in message:
                    reply = {"result": {}} if message["method"] == "ping" else {"error": {"code": -32601, "message": "method not found"}}
                    try:
                        self._send({"jsonrpc": "2.0", "id": message["id"], **reply})
                    except (OSError, ValueError):
                        break
                continue
            number = message.get("id")
            waiting = self.pending.pop(number, None) if isinstance(number, int) else None
            if waiting is not None:
                waiting.put(message)
        self.closed = True                            # stdout ended: the server is gone. Wake whoever is still waiting.
        for waiting in list(self.pending.values()):
            waiting.put(None)

    def notify(self, method: str, params: dict | None = None) -> None:
        try:
            self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})
        except (OSError, ValueError):
            pass                                      # a notification to a server that has gone is lost; the next request says so

    def request(self, method: str, params: dict, timeout: float) -> dict:
        """Send a request and wait for its answer. Raises MCPError (stopped, no answer) or ServerError (it answered with an error)."""
        number = next(self.ids)
        answer: queue.Queue = queue.Queue(maxsize=1)
        self.pending[number] = answer
        if self.closed:                               # checked after registering, so the reader can't end between the two unseen
            self.pending.pop(number, None)
            raise MCPError(self.stopped_text())
        try:
            self._send({"jsonrpc": "2.0", "id": number, "method": method, "params": params})
            message = answer.get(timeout=timeout)
        except (OSError, ValueError):
            self.pending.pop(number, None)
            raise MCPError(self.stopped_text()) from None
        except queue.Empty:
            self.pending.pop(number, None)
            self.notify("notifications/cancelled", {"requestId": number, "reason": f"no answer in {timeout:g} s"})
            raise MCPError(f"the MCP server '{self.name}' didn't answer {method} within {timeout:g} s") from None
        if message is None:
            raise MCPError(self.stopped_text())
        if "error" in message:
            error = message["error"] if isinstance(message["error"], dict) else {}
            raise ServerError(f"{error.get('message', 'unknown error')} (code {error.get('code', '?')})")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def stopped_text(self) -> str:
        try:
            code = self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            code = None
        where = f"; its log: {self.log}" if self.log else ""
        return f"the MCP server '{self.name}' has stopped" + (f" (exit code {code})" if code is not None else "") + where

    # --- the protocol ---------------------------------------------------------------------------
    def start(self, timeout: float = START_TIMEOUT) -> None:
        """Agree on a protocol version, then list the tools (page by page)."""
        self.info = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                                "clientInfo": {"name": "agent-harness", "version": __version__}}, timeout)
        version = self.info.get("protocolVersion")
        if version not in SUPPORTED:
            raise MCPError(f"the MCP server '{self.name}' speaks protocol version {version!r}; this harness speaks {', '.join(sorted(SUPPORTED))}")
        self.notify("notifications/initialized")
        if "tools" not in (self.info.get("capabilities") or {}):
            return                                    # it offers no tools (only resources or prompts, which we don't use)
        cursor = None
        for _ in range(MAX_PAGES):
            page = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
            self.tools += [t for t in page.get("tools") or [] if isinstance(t, dict) and isinstance(t.get("name"), str)]
            cursor = page.get("nextCursor")
            if not cursor:
                break

    def call(self, tool: str, arguments: dict, timeout: float = CALL_TIMEOUT) -> str:
        """Run one tool. The text for the model: the server's words never start with "Error" (the harness doesn't fence its own errors)."""
        try:
            return result_text(self.request("tools/call", {"name": tool, "arguments": arguments}, timeout))
        except ServerError as e:
            return f"Tool error: {e}"                 # written by the server: fenced like any other result
        except MCPError as e:
            return f"Error: {e}"

    def close(self) -> None:
        """Close its stdin (the protocol's way to say goodbye), then stop it if it doesn't leave."""
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            kill_tree(self.proc)
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass


def result_text(result: dict) -> str:
    """A tools/call result as text. Text is kept; images and audio are named, not shown (the model here reads text only)."""
    parts = []
    for item in result.get("content") or []:
        kind = item.get("type") if isinstance(item, dict) else None
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind == "resource":
            res = item.get("resource") if isinstance(item.get("resource"), dict) else {}
            parts.append(f"[{res.get('uri', 'resource')}]\n{res['text']}" if "text" in res else
                         f"[{res.get('uri', 'resource')}: {res.get('mimeType', 'binary data')}, not shown]")
        elif kind == "resource_link":
            parts.append(f"[link: {item.get('name', '')} {item.get('uri', '')}]".replace("  ", " "))
        else:
            parts.append(f"[{kind or 'unknown'} content{': ' + item['mimeType'] if isinstance(item, dict) and item.get('mimeType') else ''}, not shown]")
    if not parts and isinstance(result.get("structuredContent"), dict):
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    text = "\n".join(parts) or "(the tool returned nothing)"
    return f"Tool error: {text}" if result.get("isError") else text


def tool_name(server: str, tool: str) -> str:
    """mcp__<server>__<tool>, in the characters every provider accepts, at most 64 long."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"mcp__{server}__{tool}")[:64]


def make_tools(server: Server, warn=lambda text: None) -> list[Tool]:
    """A `Tool` for each tool the server listed."""
    out, seen = [], set()
    for spec in server.tools:
        name = tool_name(server.name, spec["name"])
        if name in seen:
            warn(f"MCP server '{server.name}': two tools are both called {name} here; the second ({spec['name']}) is left out")
            continue
        seen.add(name)
        text = UNSAFE.sub("", str(spec.get("description") or spec.get("title") or spec["name"])).strip()
        if len(text) > MAX_DESCRIPTION:
            text = text[:MAX_DESCRIPTION] + " [cut]"
        out.append(Tool(name=name, description=text, parameters=input_schema(spec.get("inputSchema")), fn=caller(server, spec["name"]),
                        deferrable=True, content_kind=None if server.trusted else "external"))
    return out


def caller(server: Server, remote: str):
    return lambda **arguments: server.call(remote, arguments)


def input_schema(raw) -> dict:
    """The server's JSON Schema, kept as it is except for the parts the registry reads: an object, a dict of properties, a list of required names."""
    raw = raw if isinstance(raw, dict) else {}
    props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    required = [r for r in raw.get("required", []) if isinstance(r, str)] if isinstance(raw.get("required"), list) else []
    schema = {k: v for k, v in raw.items() if k != "required"}
    schema.update(type="object", properties={k: v if isinstance(v, dict) else {} for k, v in props.items()})
    return {**schema, "required": required} if required else schema


def connect(name: str, spec: dict, cwd: Path, log_dir: Path, timeout: float = START_TIMEOUT) -> Server:
    """Start a server from its settings and list its tools. Raises MCPError. It gets the environment commands get, without secrets,
    plus the variables its "env" names: a server sees your GITHUB_TOKEN only if you say so."""
    server = Server(name, spec["command"], spec.get("args", []), spec.get("env", []), cwd, log_dir / f"mcp-{name}.log",
                    spec.get("trusted", False))
    try:
        server.start(timeout)
    except MCPError:
        server.close()
        raise
    return server
