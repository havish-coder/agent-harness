"""Lesson 51: MCP servers. A real server process (tests/mcp_server.py) on the other end of the pipe, misbehaving on request."""
import json
import sys
from pathlib import Path

import pytest

from harness import config
from harness.commands import load_commands
from harness.config import ConfigError, Settings, load_settings
from harness.mcp import (
    MAX_DESCRIPTION,
    MCPError,
    Server,
    check_servers,
    connect,
    input_schema,
    make_tools,
    result_text,
    tool_name,
)
from harness.messages import ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.security.permissions import Permissions, Rule
from harness.security.trust import set_trusted
from harness.session import Session
from harness.tools.registry import ToolRegistry
from harness.tui.plain import PlainUI
from harness.workspace import Workspace

SERVER = str(Path(__file__).with_name("mcp_server.py"))


@pytest.fixture
def start(tmp_path):
    """start(*flags, timeout=..., env=..., trusted=...) -> a connected Server, stopped after the test."""
    running = []

    def start_(*flags, timeout=10, **spec):
        server = connect("demo", {"command": sys.executable, "args": [SERVER, *flags], **spec}, tmp_path, tmp_path / "logs", timeout)
        running.append(server)
        return server
    yield start_
    for server in running:
        server.close()


def tools_of(server):
    return {t.name: t for t in make_tools(server)}


# --- the protocol ------------------------------------------------------------------------------------------------------------

def test_it_agrees_a_version_and_lists_every_page_of_tools(start):
    server = start("--page", "2", "--noise")                    # a stray line on stdout is skipped
    assert server.info["protocolVersion"] == "2025-06-18"
    assert [t["name"] for t in server.tools][:3] == ["echo", "add", "fail"] and len(server.tools) == 9


def test_a_call_returns_the_text_and_numbers_arrive_as_numbers(start):
    tools = tools_of(start())
    assert tools["mcp__demo__echo"].fn(text="héllo") == "héllo"
    assert tools["mcp__demo__add"].fn(a=2, b=40) == "42"


def test_an_error_result_is_in_the_servers_words_and_does_not_start_with_error(start):
    server = start()
    assert tools_of(server)["mcp__demo__fail"].fn() == "Tool error: it broke"          # fenced like any other result: the server wrote it
    assert server.call("no_such_tool", {}) == "Tool error: Unknown tool: no_such_tool (code -32602)"


def test_images_are_named_not_shown_and_structured_content_is_used_when_there_is_nothing_else(start):
    tools = tools_of(start())
    assert tools["mcp__demo__picture"].fn() == "[image content: image/png, not shown]\na red dot"
    assert json.loads(tools["mcp__demo__structured"].fn()) == {"answer": 42}


def test_the_server_may_ping_and_anything_else_it_asks_is_refused(start):
    assert tools_of(start("--ping"))["mcp__demo__echo"].fn(text="still here") == "still here"   # the server checks both answers


def test_a_call_with_no_answer_times_out_and_is_cancelled(start, tmp_path):
    server = start("--hang")
    assert server.call("echo", {"text": "x"}, timeout=0.5) == "Error: the MCP server 'demo' didn't answer tools/call within 0.5 s"
    assert server.call("echo", {"text": "x"}, timeout=0.5).startswith("Error:")       # it still works for the next call
    server.close()
    log = (tmp_path / "logs" / "mcp-demo.log").read_text()
    assert "cancelled 3\ncancelled 4" in log                     # the server was told (1 was initialize, 2 tools/list)


def test_a_server_that_dies_during_a_call_is_reported_with_its_exit_code_and_log(start, tmp_path):
    server = start("--crash")
    result = server.call("echo", {"text": "x"})
    assert result.startswith("Error: the MCP server 'demo' has stopped (exit code 3)") and str(tmp_path / "logs") in result
    assert server.closed and server.call("echo", {"text": "x"}).startswith("Error: the MCP server 'demo' has stopped")


def test_closing_stops_the_process(start):
    server = start()
    server.close()
    assert server.proc.poll() is not None


@pytest.mark.parametrize("flags,expected", [
    (["--version", "1999-01-01"], "speaks protocol version '1999-01-01'"),
    (["--slow", "3"], "didn't answer initialize within 0.5 s"),
])
def test_a_server_that_cant_be_used_fails_to_connect_and_is_stopped(tmp_path, flags, expected):
    with pytest.raises(MCPError, match=expected):
        connect("demo", {"command": sys.executable, "args": [SERVER, *flags]}, tmp_path, tmp_path / "logs", timeout=0.5)


def test_a_program_that_does_not_exist_is_a_clear_error(tmp_path):
    with pytest.raises(MCPError, match="can't start 'no-such-program-xyz'"):
        connect("demo", {"command": "no-such-program-xyz"}, tmp_path, tmp_path / "logs")


def test_a_server_without_tools_gives_none(start):
    assert start("--no-tools").tools == []


def test_a_server_sees_a_secret_variable_only_when_its_settings_name_it(start, monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "abc")
    monkeypatch.setenv("DEMO_COLOR", "blue")
    plain = tools_of(start())["mcp__demo__env"]
    assert plain.fn(name="DEMO_TOKEN") == "unset" and plain.fn(name="DEMO_COLOR") == "set"
    assert tools_of(start(env=["DEMO_TOKEN"]))["mcp__demo__env"].fn(name="DEMO_TOKEN") == "set"


# --- turning its tools into ours ---------------------------------------------------------------------------------------------

def test_names_are_prefixed_cleaned_capped_and_a_clash_is_left_out(start):
    warnings = []
    tools = make_tools(start(), warnings.append)
    assert "mcp__demo__dup_name" in [t.name for t in tools] and len(tools) == 8
    assert "the second (dup_name) is left out" in warnings[0]
    assert tool_name("my-server", "a.b c/d") == "mcp__my-server__a_b_c_d" and len(tool_name("s", "x" * 100)) == 64


def test_tools_ask_by_default_wait_to_be_shown_and_their_results_are_untrusted(start):
    tool = tools_of(start())["mcp__demo__add"]                   # the server says readOnlyHint: true. A hint isn't a promise.
    assert not tool.is_read_only({}) and not tool.is_concurrency_safe({}) and tool.deferrable and tool.content_kind == "external"
    assert tools_of(start(trusted=True))["mcp__demo__add"].content_kind is None


def test_descriptions_lose_terminal_codes_and_control_characters_and_are_capped(start):
    assert tools_of(start())["mcp__demo__weird"].description == "A schema with odd parts."     # it had \x1b[31m and \x07
    server = Server.__new__(Server)
    server.name, server.trusted, server.tools = "demo", False, [{"name": "long", "description": "x" * 5000}]
    assert len(make_tools(server)[0].description) == MAX_DESCRIPTION + len(" [cut]")


def test_a_schema_with_parts_the_registry_does_not_read_still_validates(start):
    tool = tools_of(start())["mcp__demo__weird"]
    assert tool.parameters["required"] == ["either"] and tool.parameters["properties"]["bad"] == {}
    registry = ToolRegistry([tool])
    found, error = registry.resolve(ToolCall("1", tool.name, {"either": 5, "maybe": None}))
    assert error is None and json.loads(registry.invoke(found, {"either": 5})) == {"either": 5}
    assert registry.resolve(ToolCall("2", tool.name, {}))[1].startswith("Error: invalid arguments")
    assert input_schema("nonsense") == {"type": "object", "properties": {}}


@pytest.mark.parametrize("result,expected", [
    ({"content": [{"type": "resource", "resource": {"uri": "file:///a.txt", "text": "hello"}}]}, "[file:///a.txt]\nhello"),
    ({"content": [{"type": "resource", "resource": {"uri": "file:///a.bin", "blob": "AAA=", "mimeType": "application/zip"}}]},
     "[file:///a.bin: application/zip, not shown]"),
    ({"content": [{"type": "resource_link", "uri": "file:///b.md", "name": "b.md"}]}, "[link: b.md file:///b.md]"),
    ({"content": [{"type": "audio", "data": "x", "mimeType": "audio/wav"}]}, "[audio content: audio/wav, not shown]"),
    ({"content": ["not an object"]}, "[unknown content, not shown]"),
    ({}, "(the tool returned nothing)"),
    ({"content": [{"type": "text", "text": "nope"}], "isError": True}, "Tool error: nope"),
])
def test_every_kind_of_content_becomes_text(result, expected):
    assert result_text(result) == expected


# --- settings ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("servers,problem", [
    ({"bad name": {"command": "x"}}, "must be 1-30 letters"),
    ({"a__b": {"command": "x"}}, "no '__'"),
    ({"a": {"args": []}}, "needs a \"command\""),
    ({"a": {"command": "x", "cwd": "/"}}, "unknown key(s) cwd"),
    ({"a": {"command": "x", "args": "--flag"}}, "must be lists of strings"),
    ({"a": {"command": "x", "env": {"TOKEN": "v"}}}, "must be lists of strings"),
    ({"a": {"command": "x", "trusted": "yes"}}, "\"trusted\" must be true or false"),
])
def test_server_settings_are_checked(servers, problem):
    assert problem in check_servers(servers, "user")[0]
    assert check_servers({"ok-1_x": {"command": "npx", "args": ["-y", "pkg"], "env": ["TOKEN"], "trusted": True}}, "user") == []


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_only_your_user_settings_can_start_a_server(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    ws = tmp_path / "proj"
    write(tmp_path / "home" / "settings.json", {"mcp_servers": {"mine": {"command": "a"}}})
    write(ws / ".harness" / "settings.json", {"mcp_servers": {"theirs": {"command": "b"}}})
    write(ws / ".harness" / "settings.local.json", {"mcp_servers": {"shipped": {"command": "c"}}})
    settings, warnings = load_settings(ws, environ={})
    assert settings.mcp_servers == {"mine": {"command": "a"}}
    assert any("project settings can't set 'mcp_servers' (it starts programs" in w and "user settings" in w for w in warnings)
    assert any("settings.local.json can't set 'mcp_servers'" in w for w in warnings)


def test_a_broken_server_setting_is_an_error_naming_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    write(tmp_path / "home" / "settings.json", {"mcp_servers": {"x": {"command": ""}}})
    with pytest.raises(ConfigError, match="user: mcp_servers\\['x'\\] needs"):
        load_settings(tmp_path / "proj", environ={})


# --- permissions -------------------------------------------------------------------------------------------------------------

def test_a_rule_can_name_one_tool_or_a_whole_server(tmp_path):
    whole, one, near = Rule.parse("mcp__demo", "deny"), Rule.parse("mcp__demo__echo", "allow"), Rule.parse("mcp__dem", "deny")
    assert whole.names("mcp__demo__echo") and whole.names("mcp__demo__add") and not whole.names("mcp__demo2__echo")
    assert one.names("mcp__demo__echo") and not one.names("mcp__demo__add") and not near.names("mcp__demo__echo")
    perms = Permissions(Workspace(tmp_path), rules=[whole, near])
    assert perms.unknown_tools(["mcp__demo__echo"]) == ["permission rule mcp__dem (session) names an unknown tool 'mcp__dem'"]


# --- the session -------------------------------------------------------------------------------------------------------------

class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.warnings = []

    def __call__(self, kind, data):
        pass

    def warn(self, text_):
        self.warnings.append(text_)

    def info(self, text_):
        pass


class Approver:
    def __init__(self, answer=True):
        self.answer, self.asked = answer, []

    def __call__(self, call, tool, decision=None):
        self.asked.append(call.name)
        return self.answer


@pytest.fixture
def session(tmp_path, monkeypatch):
    made = []

    def make(servers=None, approver=None, **settings):
        monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
        root = tmp_path / "proj"
        root.mkdir(parents=True, exist_ok=True)
        set_trusted(root, config.USER_DIR, True)
        servers = {"demo": {"command": sys.executable, "args": [SERVER]}} if servers is None else servers
        base = {"save_chats": False, "auto_memory": "off", "journal": "off", "file_history": False, "tool_search": "off", "mcp_servers": servers}
        s = Session(Settings(**(base | settings)), Workspace(root), Quiet(), approver or Approver())
        s.agent.stream = False
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


def results(s):
    return [m.content for m in s.agent.messages if m.role == "tool"]


def test_the_model_calls_a_server_tool_after_asking_and_reads_a_fenced_result(session):
    approver = Approver()
    s = session(approver=approver)
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("1", "mcp__demo__echo", {"text": "hi"})), text("done")])
    assert s.agent.run("say hi") == "done"
    assert approver.asked == ["mcp__demo__echo"]
    assert results(s)[0].startswith('<untrusted source="mcp__demo__echo') and "\nhi\n" in results(s)[0]
    assert s.permissions.taint.active


def test_after_a_server_result_a_blanket_approval_for_its_tool_asks_again(session):
    approver = Approver()
    s = session(approver=approver)
    s.permissions.rules.append(Rule.parse("mcp__demo__echo", "allow", "user"))
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("1", "mcp__demo__echo", {"text": "a"})),
                                         tool_calls(ToolCall("2", "mcp__demo__echo", {"text": "b"})), text("done")])
    s.agent.run("echo twice")
    assert approver.asked == ["mcp__demo__echo"]                # the first ran on the rule; after its result, the second asked


def test_a_trusted_servers_results_are_not_fenced_and_taint_nothing(session):
    s = session({"demo": {"command": sys.executable, "args": [SERVER], "trusted": True}})
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("1", "mcp__demo__echo", {"text": "hi"})), text("done")])
    s.agent.run("say hi")
    assert results(s) == ["hi"] and not s.permissions.taint.active


def test_a_rule_for_the_whole_server_denies_all_its_tools(session):
    s = session()
    s.permissions.rules.append(Rule.parse("mcp__demo", "deny", "user"))
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("1", "mcp__demo__add", {"a": 1, "b": 2})), text("ok")])
    s.agent.run("add")
    assert "denied by the rule mcp__demo (user)" in results(s)[0]


def test_a_server_that_fails_is_reported_and_the_session_works_without_it(session):
    s = session({"broken": {"command": "no-such-program-xyz"}, "demo": {"command": sys.executable, "args": [SERVER]}})
    assert any("the MCP server 'broken' didn't start: can't start" in w for w in s.ui.warnings)
    assert "mcp__demo__echo" in s.agent.tools.names() and isinstance(s.mcp["broken"], str)


def test_closing_the_session_stops_its_servers(session):
    s = session()
    server = s.mcp["demo"]
    s.close()
    assert server.proc.poll() is not None


def test_a_servers_few_tools_are_shown_even_when_ours_are_held_back(session):
    s = session(tool_search="auto")                              # 8 tools, 385 tokens: under 15% of 8,192, though our own tools are over it
    assert "web_fetch" in s.agent.tools.deferred
    assert "mcp__demo__echo" not in s.agent.tools.deferred and "mcp__demo__echo" in [t["name"] for t in s.agent.tools.schemas()]


def test_a_server_with_many_tools_waits_for_tool_search(session):
    s = session({"demo": {"command": sys.executable, "args": [SERVER, "--many", "30"]}}, tool_search="auto")     # 1,682 tokens
    assert "mcp__demo__echo" in s.agent.tools.deferred and "mcp__demo__echo" in s.prompt.text
    assert "mcp__demo__echo" not in [t["name"] for t in s.agent.tools.schemas()]


def test_tool_search_on_holds_back_every_server_tool_and_off_none(session):
    assert "mcp__demo__echo" in session(tool_search="on").agent.tools.deferred
    assert not session(tool_search="off").agent.tools.deferred


def test_the_mcp_command_lists_servers_and_their_tools(session):
    s = session({"broken": {"command": "no-such-program-xyz"}, "demo": {"command": sys.executable, "args": [SERVER]}})
    run = load_commands(s.ws.root).get("mcp").run
    listing = run(s, "")
    assert "demo           running  8 tools  (test-server 1.0)  log: " in listing          # the name it sent had a screen-clearing code
    assert "broken         failed   can't start" in listing
    assert "mcp__demo__echo\n    Say the text back." in run(s, "demo")
    assert run(s, "nope") == "no MCP server 'nope' (yours: broken, demo)"
    assert "didn't start" in run(s, "broken")


def test_with_no_servers_the_command_says_how_to_add_one(session):
    s = session({})
    assert "add one to \"mcp_servers\"" in load_commands(s.ws.root).get("mcp").run(s, "")
