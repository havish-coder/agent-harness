"""Lesson 50: tool search. Definitions are shown when they are needed."""
import json

import pytest

from harness import config
from harness.commands import load_commands
from harness.config import ConfigError, Settings, load_settings
from harness.messages import ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.security.trust import set_trusted
from harness.session import Session
from harness.tools.base import tool
from harness.tools.registry import ToolRegistry
from harness.toolsearch import (
    MAX_RESULTS,
    TOOL_SHARE,
    catalog_text,
    make_search_tool,
    schema_tokens,
    search,
    stem,
    words,
)
from harness.tui.plain import PlainUI
from harness.workspace import Workspace


def fake(name, description, deferrable=True, read_only=True):
    @tool(name=name, read_only=read_only, deferrable=deferrable)
    def f(x: str = "") -> str:
        """placeholder"""
        return f"{name} ran"
    f.description = description
    return f


CATALOG = [
    fake("calendar_create_event", "Create an event on the user's calendar with a title and a time."),
    fake("calendar_list_events", "List the events on the user's calendar for a day."),
    fake("ticket_create", "Open a new ticket in the issue tracker with a title and a description."),
    fake("ticket_comment", "Add a comment to an existing ticket."),
    fake("weather_forecast", "Get the weather forecast for a city."),
    fake("web_fetch", "Fetch one web page and return its text."),
    fake("remember", "Save a note for later chats in this project."),
    fake("send_email", "Send an email to someone."),
]


# --- the search --------------------------------------------------------------------------------------------------------------

def test_words_are_lower_case_stemmed_and_split_on_underscores():
    assert words("Create_Event: creating events") == ["create", "event", "creat", "event"]
    assert stem("fetching") == "fetch" and stem("tickets") == "ticket" and stem("is") == "is" and stem("bus") == "bus"


def test_a_name_match_beats_a_description_match():
    in_description, in_name = fake("alpha_tool", "Does something with a zebra."), fake("zebra_tool", "Does something else.")
    found = search([in_description, in_name], "zebra")
    assert [m.tool.name for m in found] == ["zebra_tool", "alpha_tool"] and [m.score for m in found] == [3, 1]
    assert {m.tool.name for m in search(CATALOG, "ticket")[:2]} == {"ticket_create", "ticket_comment"}


def test_the_best_tool_for_what_you_want_to_do_comes_first():
    assert search(CATALOG, "create a calendar event")[0].tool.name == "calendar_create_event"
    assert search(CATALOG, "what is the weather in Paris")[0].tool.name == "weather_forecast"
    assert search(CATALOG, "fetching a web page")[0].tool.name == "web_fetch"
    assert search(CATALOG, "save a note")[0].tool.name == "remember"
    assert search(CATALOG, "email Sam")[0].tool.name == "send_email"


def test_nothing_matching_returns_nothing_and_results_are_limited():
    assert search(CATALOG, "quantum entanglement") == [] and search(CATALOG, "") == []
    many = [fake(f"tool_{n}", "common words here") for n in range(20)]
    assert len(search(many, "common words")) == MAX_RESULTS


def test_ties_are_broken_by_name_so_the_answer_is_stable():
    a, b = fake("zeta_tool", "does the thing"), fake("alpha_tool", "does the thing")
    assert [m.tool.name for m in search([a, b], "thing")] == ["alpha_tool", "zeta_tool"]


def test_the_catalog_names_the_tools_and_stays_within_its_budget():
    out = catalog_text(CATALOG)
    assert out.startswith("More tools exist but are not shown.") and "calendar_create_event" in out and "send_email" in out
    cut = catalog_text([fake(f"a_rather_long_tool_name_{n:03}", "x") for n in range(100)], max_tokens=100)
    assert "and " in cut and "more." in cut and len(cut) < 700
    assert catalog_text([]) == ""


# --- the registry --------------------------------------------------------------------------------------------------------------

def registry_with_held():
    registry = ToolRegistry(CATALOG + [fake("read_file", "Read a file.", deferrable=False)])
    registry.hold_back([t.name for t in CATALOG])
    return registry


def test_held_back_tools_are_not_in_the_schemas_until_loaded():
    registry = registry_with_held()
    assert [s["name"] for s in registry.schemas()] == ["read_file"]
    registry.load(["weather_forecast", "nope"])
    assert [s["name"] for s in registry.schemas()] == ["weather_forecast", "read_file"] or {s["name"] for s in registry.schemas()} == {"weather_forecast", "read_file"}
    assert "weather_forecast" not in [t.name for t in registry.held_back()] and registry.loaded == {"weather_forecast"}


def test_calling_a_tool_that_is_not_loaded_says_to_search_first():
    registry = registry_with_held()
    found, error = registry.resolve(ToolCall("1", "send_email", {}))
    assert found is None and "hasn't been loaded yet" in error and "tool_search" in error
    registry.load(["send_email"])
    assert registry.resolve(ToolCall("1", "send_email", {}))[0] is not None


def test_unknown_tool_errors_list_only_what_is_shown():
    registry = registry_with_held()
    _, error = registry.resolve(ToolCall("1", "nope", {}))
    assert "Available tools: read_file" in error and "send_email" not in error


def test_holding_back_nothing_shows_everything_again():
    registry = registry_with_held()
    registry.hold_back([])
    assert len(registry.schemas()) == len(CATALOG) + 1 and registry.held_back() == []


def test_a_tool_that_is_not_enabled_is_not_held_back_either():
    off = fake("off_tool", "disabled")
    off.enabled = lambda: False
    registry = ToolRegistry([off])
    registry.hold_back(["off_tool"])
    assert registry.held_back() == []


# --- the tool ---------------------------------------------------------------------------------------------------------------------

def test_tool_search_finds_loads_and_shows_the_signatures():
    registry = registry_with_held()
    registry.add(make_search_tool(lambda: registry)[0])
    out = registry.get("tool_search").fn(query="create a calendar event")
    assert out.startswith("Loaded: calendar_create_event") and "calendar_create_event(x: string" in out and "You can call them now." in out
    assert "calendar_create_event" in {s["name"] for s in registry.schemas()}


def test_a_search_with_no_match_says_what_exists():
    registry = registry_with_held()
    t = make_search_tool(lambda: registry)[0]
    out = t.fn(query="quantum entanglement")
    assert out.startswith("No tool matched 'quantum entanglement'") and "ticket_create" in out and registry.loaded == set()


def test_the_search_tool_is_offered_only_while_tools_are_held_back():
    registry = ToolRegistry(CATALOG)
    registry.add(make_search_tool(lambda: registry)[0])
    assert "tool_search" not in [s["name"] for s in registry.schemas()]
    registry.hold_back([t.name for t in CATALOG])
    assert "tool_search" in [s["name"] for s in registry.schemas()]
    registry.load([t.name for t in CATALOG])
    assert "tool_search" not in [s["name"] for s in registry.schemas()]               # nothing left to find


def test_the_search_tool_never_asks_and_never_changes_anything():
    t = make_search_tool(lambda: ToolRegistry())[0]
    assert t.is_read_only({}) and t.name == "tool_search" and t.parameters["required"] == ["query"]


# --- the session ---------------------------------------------------------------------------------------------------------------------

class Quiet(PlainUI):
    def __call__(self, kind, data):
        pass

    def warn(self, text_):
        pass

    def info(self, text_):
        pass


def make_session(tmp_path, monkeypatch, **settings):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    set_trusted(root, config.USER_DIR, True)
    base = {"save_chats": False, "auto_memory": "ask", "journal": "off", "file_history": False}
    s = Session(Settings(**(base | settings)), Workspace(root), Quiet(), lambda c, t, d=None: True)
    s.agent.stream = False
    return s


def names(s):
    return [t["name"] for t in s.agent.tools.schemas()]


def test_the_rarely_used_tools_are_the_deferrable_ones(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, tool_search="off")
    deferrable = {t.name for t in s.agent.tools if t.deferrable}
    assert {"remember", "recall", "forget", "web_fetch", "task_output", "task_stop"} <= deferrable
    assert not deferrable & {"read_file", "edit_file", "run_shell", "grep", "delegate", "ask_user", "todo_write"}


def test_auto_holds_tools_back_in_a_small_window(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, web_fetch=True)               # 8,192: the definitions are well over 15%
    assert schema_tokens([t for t in s.agent.tools if t.is_enabled()]) > TOOL_SHARE * s.context.window
    assert {"remember", "web_fetch", "task_output"} <= s.agent.tools.deferred
    assert "remember" not in names(s) and "tool_search" in names(s) and "read_file" in names(s)


def test_auto_does_nothing_in_a_big_window(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, context_window=200_000, web_fetch=True)
    assert s.agent.tools.deferred == set() and "remember" in names(s) and "tool_search" not in names(s)


def test_on_always_holds_back_and_off_never_does(tmp_path, monkeypatch):
    on = make_session(tmp_path, monkeypatch, context_window=200_000, tool_search="on")
    assert "remember" in on.agent.tools.deferred and "remember" not in names(on)
    (tmp_path / "b").mkdir()
    off = make_session(tmp_path / "b", monkeypatch, tool_search="off")
    assert off.agent.tools.deferred == set() and "remember" in names(off)


def test_the_prompt_names_the_held_back_tools_and_does_not_change_when_one_is_loaded(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "more tools" in [p.name for p in s.prompt.parts] and "remember" in s.prompt.text and "tool_search(query)" in s.prompt.text
    before = s.agent.messages[0].content
    s.agent.tools.load(["remember"])
    assert s.agent.messages[0].content == before                            # a stable prefix: the server's cache survives a load


def test_the_model_searches_loads_and_then_calls(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, auto_memory="on")
    s.agent.provider = ScriptedProvider([
        tool_calls(ToolCall("a", "remember", {"title": "x", "description": "d", "kind": "user", "text": "t"})),       # not loaded yet
        tool_calls(ToolCall("b", "tool_search", {"query": "save a note"})),
        text("ok")])
    s.agent.run("remember that I like tabs")
    results = [m.content for m in s.agent.messages if m.role == "tool"]
    assert "hasn't been loaded yet" in results[0] and results[1].startswith("Loaded: remember") and "remember" in names(s)


def test_a_loaded_tool_is_sent_to_the_model_on_the_very_next_call(tmp_path, monkeypatch):
    # The first version built the tool list once per request: the model was told "you can call them now" and wasn't sent them until the user's
    # next message, so it searched again and again (the lab: right tool first 0 of 30). A scripted model doesn't care what it is sent; this checks it.
    s = make_session(tmp_path, monkeypatch, auto_memory="on")
    s.agent.provider = provider = ScriptedProvider([tool_calls(ToolCall("b", "tool_search", {"query": "save a note"})), text("ok")])
    s.agent.run("remember that I like tabs")
    sent = [[t["name"] for t in tools] for _, tools in provider.requests]
    assert "remember" not in sent[0] and "remember" in sent[1]


def test_a_held_back_tool_is_still_judged_by_the_same_rules(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, web_fetch=True)
    s.agent.tools.load(["web_fetch"])
    from harness.security.permissions import Rule
    s.permissions.rules.append(Rule.parse("web_fetch", "deny", "test"))
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("w", "web_fetch", {"url": "http://example.com"})), text("ok")])
    s.agent.run("fetch it")
    assert "denied by the rule" in [m.content for m in s.agent.messages if m.role == "tool"][0]


def test_a_new_chat_has_found_no_tools_yet(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.tools.load(["remember"])
    s.reset()
    assert s.agent.tools.loaded == set() and "remember" not in names(s)


def test_a_resumed_chat_has_the_tools_it_found_before(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, save_chats=True)
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("b", "tool_search", {"query": "save a note"})), text("ok")])
    s.agent.run("find a tool")
    assert "remember" in names(s)
    s.close()
    again = make_session(tmp_path, monkeypatch, save_chats=True)
    assert "remember" not in names(again)
    again.resume(again.chats()[0])
    assert "remember" in names(again)


def test_the_tools_command_marks_what_is_held_back_and_hides_what_is_not_available(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    out = load_commands(s.ws.root).parse("/tools")[0].run(s, "")
    assert "remember" in out and "held back: found with tool_search" in out and "exit_plan_mode" not in out and "use_skill" not in out


def test_the_setting_is_checked_and_a_project_may_choose_it(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    (root / ".harness").mkdir(parents=True)
    (root / ".harness" / "settings.json").write_text(json.dumps({"tool_search": "off"}), encoding="utf-8")
    settings, warnings = load_settings(root)
    assert settings.tool_search == "off" and not warnings
    (root / ".harness" / "settings.json").write_text(json.dumps({"tool_search": "sometimes"}), encoding="utf-8")
    with pytest.raises(ConfigError, match="'tool_search' must be one of auto, on, off"):
        load_settings(root)
