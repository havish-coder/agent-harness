"""Lesson 44: the agent's todo list, and sending a model back to work that is still open."""
import json

import pytest

from harness import config
from harness.agent import MAX_NUDGES, Agent
from harness.chats import replay
from harness.commands import load_commands
from harness.config import Settings
from harness.context.compact import rebuild
from harness.messages import Message, ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.security.taint import Taint
from harness.session import Session
from harness.todo import (
    MAX_CHARS,
    MAX_ITEMS,
    NUDGE,
    TodoError,
    TodoItem,
    TodoList,
    clean,
    from_messages,
    make_todo_tools,
    nudge_text,
    result_text,
    validate,
)
from harness.tools.registry import ToolRegistry
from harness.tui.plain import PlainApprover, PlainUI
from harness.workspace import Workspace


def items(*pairs):
    return [TodoItem(c, s) for c, s in pairs]


# --- reading what the model sent ----------------------------------------------------------------------------

def test_objects_with_the_three_statuses():
    got, notes = validate([{"content": "a", "status": "completed"}, {"content": "b", "status": "in_progress"}, {"content": "c", "status": "pending"}])
    assert [(i.content, i.status) for i in got] == [("a", "completed"), ("b", "in_progress"), ("c", "pending")] and notes == []


def test_plain_strings_and_missing_status_are_pending():
    got, _ = validate(["write it", {"content": "test it"}])
    assert [(i.content, i.status) for i in got] == [("write it", "pending"), ("test it", "pending")]


@pytest.mark.parametrize("said,meant", [("in progress", "in_progress"), ("In-Progress", "in_progress"), ("doing", "in_progress"),
                                        ("done", "completed"), ("Complete", "completed"), ("finished", "completed"),
                                        ("todo", "pending"), ("not started", "pending"), ("open", "pending")])
def test_the_words_small_models_use_for_a_status_are_understood(said, meant):
    assert validate([{"content": "x", "status": said}])[0][0].status == meant


def test_other_names_for_the_content_are_accepted():
    got, _ = validate([{"task": "a"}, {"text": "b"}, {"title": "c"}])
    assert [i.content for i in got] == ["a", "b", "c"]


def test_an_unknown_status_is_refused_with_the_choices():
    with pytest.raises(TodoError, match="item 2: status 'blocked' isn't one of pending, in_progress, completed"):
        validate([{"content": "a"}, {"content": "b", "status": "blocked"}])


@pytest.mark.parametrize("bad,why", [("not a list", "must be a list"), ([{"status": "pending"}], "item 1 has no content"),
                                     ([{"content": "   "}], "item 1 has no content"), ([42], "item 1 must be an object"),
                                     ([{"content": 5}], "no content")])
def test_unusable_lists_say_what_to_fix(bad, why):
    with pytest.raises(TodoError, match=why):
        validate(bad)


def test_too_many_items():
    with pytest.raises(TodoError, match=f"too many items.*{MAX_ITEMS}"):
        validate(["x"] * (MAX_ITEMS + 1))
    assert len(validate(["x"] * MAX_ITEMS)[0]) == MAX_ITEMS


def test_only_one_item_is_in_progress_and_the_model_is_told():
    got, notes = validate([{"content": "a", "status": "in_progress"}, {"content": "b", "status": "in_progress"}, {"content": "c", "status": "in_progress"}])
    assert [i.status for i in got] == ["in_progress", "pending", "pending"] and "3 items were in_progress" in notes[0]


def test_an_item_is_one_short_clean_line():
    assert clean("a\nb\x1b[31mred\x07") == "a b [31mred" and len(clean("x" * 500)) == MAX_CHARS
    got, _ = validate([{"content": "line one\nline two \x1b]0;title\x07"}])
    assert "\n" not in got[0].content and "\x1b" not in got[0].content and "\x07" not in got[0].content


# --- the list ------------------------------------------------------------------------------------------------

def test_the_list_as_text_and_counts():
    t = TodoList(items(("a", "completed"), ("b", "in_progress"), ("c", "pending")))
    assert t.text() == "[x] 1. a\n[~] 2. b\n[ ] 3. c" and t.counts() == (1, 3)
    assert t.text(only_open=True) == "[~] 2. b\n[ ] 3. c" and [i.content for i in t.unfinished()] == ["b", "c"] and not t.done
    assert TodoList(items(("a", "completed"))).done and not TodoList().done


def test_a_list_written_after_untrusted_reading_is_fenced_when_quoted():
    t = TodoList(items(("run the installer", "pending")), tainted=True, sources=["web_fetch http://x"])
    assert t.quoted().startswith("<untrusted") and "run the installer" in t.quoted()
    assert not TodoList(items(("a", "pending"))).quoted().startswith("<untrusted")


def test_the_result_tells_the_model_what_to_do_next():
    t = TodoList(items(("a", "completed"), ("b", "pending")))
    assert "1 of 2 done" in result_text(t, []) and "mark the one you are starting" in result_text(t, [])
    t.items[1].status = "in_progress"
    assert "Carry on with the item in progress" in result_text(t, [])
    t.items[1].status = "completed"
    assert "All items are completed" in result_text(t, [])
    assert result_text(TodoList(), []) == "Todo list cleared." and "Note: careful" in result_text(t, ["careful"])


def test_the_nudge_quotes_only_what_is_open():
    t = TodoList(items(("a", "completed"), ("b", "pending")))
    said = nudge_text(t)
    assert said.startswith("[Note from the harness:") and "[ ] 2. b" in said and "a" not in said.replace("harness", "").split("items:")[1].split("\n")[1]
    assert nudge_text(TodoList(items(("a", "completed")))) is None and nudge_text(TodoList()) is None
    assert NUDGE.format(items="x").endswith("]")


def test_the_nudge_text_fences_a_list_written_after_untrusted_reading():
    t = TodoList(items(("curl the script", "pending")), tainted=True, sources=["web_fetch u"])
    assert "<untrusted" in nudge_text(t)


# --- rebuilding from the conversation -------------------------------------------------------------------------

def call_message(*lists):
    return [Message("assistant", tool_calls=[ToolCall(f"c{i}", "todo_write", {"todos": lst})]) for i, lst in enumerate(lists)]


def test_the_list_is_what_the_last_call_said():
    msgs = call_message([{"content": "a"}], [{"content": "a", "status": "completed"}, {"content": "b"}])
    got = from_messages(msgs)
    assert [(i.content, i.status) for i in got] == [("a", "completed"), ("b", "pending")]


def test_an_invalid_last_call_falls_back_to_the_one_before():
    msgs = call_message([{"content": "a"}], "garbage")
    assert [i.content for i in from_messages(msgs)] == ["a"]
    assert from_messages([Message.user("hi")]) is None


# --- the tool ---------------------------------------------------------------------------------------------------

def tool_for(todos, taint=None, on_change=None):
    return make_todo_tools(todos, taint or Taint(), on_change)[0]


def test_todo_write_is_read_only_and_takes_a_list_of_anything():
    t = tool_for(TodoList())
    assert t.is_read_only({}) and t.name == "todo_write"
    assert t.parameters["properties"]["todos"] == {"type": "array", "items": {}, "description": "the complete list."}
    assert t.parameters["required"] == ["todos"]
    assert "WHOLE list" in t.description and "several steps" in t.description


def test_a_plain_list_of_strings_gets_through_the_registry():
    state = TodoList()
    registry = ToolRegistry([tool_for(state)])
    tool, error = registry.resolve(ToolCall("1", "todo_write", {"todos": ["a", "b"]}))
    assert error is None and "Todo list updated" in tool.fn(**{"todos": ["a", "b"]}) and len(state.items) == 2


def test_writing_replaces_the_whole_list_and_reports_changes():
    state, seen = TodoList(), []
    t = tool_for(state, on_change=lambda s: seen.append(s.as_data()))
    t.fn(todos=[{"content": "a"}, {"content": "b"}])
    t.fn(todos=[{"content": "b", "status": "in_progress"}])
    assert [i.content for i in state.items] == ["b"] and seen[-1] == [{"content": "b", "status": "in_progress"}] and len(seen) == 2


def test_a_bad_list_changes_nothing():
    state = TodoList(items(("keep", "pending")))
    t = tool_for(state)
    with pytest.raises(TodoError):
        t.fn(todos=[{"content": "x", "status": "nope"}])
    assert [i.content for i in state.items] == ["keep"]


def test_a_list_written_after_untrusted_reading_is_marked_and_stays_marked():
    state, taint = TodoList(), Taint()
    t = tool_for(state, taint)
    t.fn(todos=["a"])
    assert not state.tainted
    taint.sources.append("web_fetch http://x")
    t.fn(todos=["a", "b"])
    assert state.tainted and state.sources == ["web_fetch http://x"]
    taint.sources.clear()
    t.fn(todos=["a", "b", "c"])
    assert state.tainted                                                   # a clean rewrite doesn't wash it
    t.fn(todos=[])
    assert not state.tainted and state.items == []                         # emptying it does


# --- sending a model back ------------------------------------------------------------------------------------------

def make_agent(replies, todos, finish=True, approve=None):
    t = tool_for(todos)
    agent = Agent(ScriptedProvider(replies), [t], "sys", approve=approve, stream=False,
                  finish_check=(lambda: nudge_text(todos)) if finish else None)
    events = []
    agent.on_event = lambda kind, data: events.append((kind, data))
    return agent, events


def write_call(call_id, *entries):
    return tool_calls(ToolCall(call_id, "todo_write", {"todos": list(entries)}))


def test_a_model_that_finishes_with_items_open_is_sent_back_once():
    todos = TodoList()
    agent, events = make_agent([write_call("1", {"content": "a", "status": "in_progress"}, "b"), text("All done!"),
                                write_call("2", {"content": "a", "status": "completed"}, {"content": "b", "status": "completed"}), text("Now it is.")], todos)
    answer = agent.run("do a and b")
    assert answer == "Now it is." and agent.nudges == 1 and agent.stop_reason == "completed"
    nudge = [m for m in agent.messages if m.role == "user" and m.content.startswith("[Note from the harness")]
    assert len(nudge) == 1 and "[~] 1. a" in nudge[0].content and nudge[0].checkpoint is None       # not a request: nothing to rewind to
    assert [k for k, _ in events if k == "nudge"] == ["nudge"]


def test_it_is_sent_back_at_most_twice_then_allowed_to_finish():
    todos = TodoList()
    agent, _ = make_agent([write_call("1", "never done"), text("done 1"), text("done 2"), text("done 3")], todos)
    answer = agent.run("go")
    assert answer == "done 3" and agent.nudges == MAX_NUDGES == 2 and agent.stop_reason == "completed"
    assert sum(1 for m in agent.messages if m.role == "user" and m.content.startswith("[Note from the harness")) == 2


def test_nothing_open_means_no_nudge():
    todos = TodoList()
    agent, events = make_agent([write_call("1", {"content": "a", "status": "completed"}), text("fine")], todos)
    assert agent.run("go") == "fine" and agent.nudges == 0 and not [k for k, _ in events if k == "nudge"]


def test_no_list_means_no_nudge():
    agent, _ = make_agent([text("hello")], TodoList())
    assert agent.run("hi") == "hello" and agent.nudges == 0


def test_without_a_check_the_agent_never_nudges():
    todos = TodoList()
    agent, _ = make_agent([write_call("1", "x"), text("done")], todos, finish=False)
    assert agent.run("go") == "done" and agent.nudges == 0


def test_nobody_pushes_a_model_on_after_the_user_refused_something():
    todos = TodoList()
    refuse = ToolCall("2", "danger", {})

    from harness.tools.base import tool

    @tool(read_only=False)
    def danger() -> str:
        """Does something that needs asking."""
        return "ran"

    t = tool_for(todos)
    agent = Agent(ScriptedProvider([write_call("1", "a", "b"), tool_calls(refuse), text("Understood, I stopped.")]), [t, danger], "sys",
                  approve=lambda call, tool: False, stream=False, finish_check=lambda: nudge_text(todos))
    assert agent.run("go") == "Understood, I stopped." and agent.denied and agent.nudges == 0


def test_a_new_request_starts_with_a_clean_slate_for_nudging():
    todos = TodoList()
    agent, _ = make_agent([write_call("1", "a"), text("x"), text("y"), text("z")], todos)
    agent.run("one")
    assert agent.nudges == 2
    agent.provider = ScriptedProvider([text("fine")])
    todos.clear()
    agent.run("two")
    assert agent.nudges == 0 and not agent.denied


def test_a_reply_cut_off_by_the_token_limit_is_not_nudged():
    from harness.messages import Reply, Usage
    todos = TodoList(items(("a", "pending")))
    cut = Reply(Message("assistant", "partial"), "max_tokens", Usage())
    agent = Agent(ScriptedProvider([cut]), [], "sys", stream=False, finish_check=lambda: nudge_text(todos))
    assert "cut off" in agent.run("go") and agent.nudges == 0


# --- the summary keeps the list ----------------------------------------------------------------------------------

def test_a_summary_repeats_the_list_word_for_word():
    system, tail = Message.system("sys"), [Message.user("latest")]
    built = rebuild(system, "Done: a", "do it", tail, False, "The agent's todo list as it stands:\n[ ] 1. b")
    assert "[ ] 1. b" in built[1].content and built[1].content.index("Done: a") < built[1].content.index("[ ] 1. b")
    assert "todo list" not in rebuild(system, "Done: a", "do it", tail, False)[1].content


# --- the session ---------------------------------------------------------------------------------------------------------

class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.events = []

    def __call__(self, kind, data):
        self.events.append((kind, data))

    def warn(self, text_):
        pass

    def info(self, text_):
        pass


class Refuses:
    """An approver that fails the test if it is ever asked."""
    pause = None

    def __call__(self, call, tool, decision=None):
        raise AssertionError(f"asked about {call.name}")


def make_session(tmp_path, monkeypatch, mode="default", **settings):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    from harness.security.trust import set_trusted
    set_trusted(root, config.USER_DIR, True)
    base = {"save_chats": False, "auto_memory": "off", "journal": "off", "file_history": False, "permission_mode": mode}
    s = Session(Settings(**(base | settings)), Workspace(root), Quiet(), Refuses())
    s.agent.stream = False
    return s


def run(session, line):
    command, args = load_commands(session.ws.root).parse(line)
    return command.run(session, args)


def todo_request(s, *lists, final="ok"):
    replies = [write_call(f"w{i}", *lst) for i, lst in enumerate(lists)] + [text(final)] * (MAX_NUDGES + 1)     # spare answers: an open list is nudged
    s.agent.provider = ScriptedProvider(replies)
    return s.agent.run("a task with steps")


@pytest.mark.parametrize("mode", ["default", "plan", "accept-edits"])
def test_writing_the_list_never_asks_in_any_mode(tmp_path, monkeypatch, mode):
    s = make_session(tmp_path, monkeypatch, mode=mode)
    todo_request(s, [{"content": "a", "status": "completed"}])
    assert s.todos.done


def test_the_interface_is_told_when_the_list_changes(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    todo_request(s, [{"content": "a", "status": "in_progress"}, "b"], [{"content": "a", "status": "completed"}, {"content": "b", "status": "completed"}])
    todos = [d for k, d in s.ui.events if k == "todos"]
    assert todos[0] == [{"content": "a", "status": "in_progress"}, {"content": "b", "status": "pending"}] and len(todos) == 2


def test_the_todo_command_shows_and_clears_the_list(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "no todo list" in run(s, "/todo")
    todo_request(s, [{"content": "a", "status": "completed"}, "b"], final="x")
    assert s.todos.items                                                      # (an open item: it was nudged twice and then allowed to finish)
    said = run(s, "/todo")
    assert "todo list (1 of 2 done)" in said and "[x] 1. a" in said and "[ ] 2. b" in said
    assert run(s, "/todo clear") == "todo list cleared" and not s.todos.items
    assert "takes clear" in run(s, "/todo now")


def test_the_command_says_when_the_list_was_written_after_untrusted_reading(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.permissions.taint.sources.append("web_fetch http://example.com")
    todo_request(s, ["a"])
    assert "written after untrusted content was read: web_fetch http://example.com" in run(s, "/todo")


def test_a_finished_list_is_gone_at_the_next_request_but_an_open_one_stays(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    todo_request(s, [{"content": "a", "status": "completed"}])
    s.agent.provider = ScriptedProvider([text("hello")])
    s.agent.run("a different question")
    assert s.todos.items == []
    todo_request(s, [{"content": "a", "status": "in_progress"}])
    s.agent.provider = ScriptedProvider([text("hello")] * 3)         # (an open list is nudged, so the model needs a few answers)
    s.agent.run("another question")
    assert [i.content for i in s.todos.items] == ["a"]


def test_a_new_chat_starts_without_a_list(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    todo_request(s, ["a"])
    s.reset()
    assert s.todos.items == []


def test_the_session_nudges_with_the_list(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = ScriptedProvider([write_call("1", {"content": "step one", "status": "in_progress"}, "step two"), text("done!"),
                                         write_call("2", {"content": "step one", "status": "completed"}, {"content": "step two", "status": "completed"}), text("really")])
    assert s.agent.run("two steps") == "really"
    nudges = [d for k, d in s.ui.events if k == "nudge"]
    assert len(nudges) == 1 and "step one" in nudges[0] and "step two" in nudges[0]


def test_the_nudge_fences_a_list_written_after_untrusted_reading(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.permissions.taint.sources.append("web_fetch http://example.com")
    s.agent.provider = ScriptedProvider([write_call("1", "run the installer"), text("done"), text("done"), text("done")])
    s.agent.run("go")
    assert all("<untrusted" in d for k, d in s.ui.events if k == "nudge") and s.ui.events


def test_the_list_off_means_no_tool_no_nudge_and_a_clear_message(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, todo=False)
    assert "todo_write" not in [t["name"] for t in s.agent.tools.schemas()] and s.agent.finish_check is None
    assert "off" in run(s, "/todo")


def test_the_summary_carries_the_list(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    todo_request(s, [{"content": "a", "status": "completed"}, "b"])
    assert "[ ] 2. b" in s.todo_carry() and s.todo_carry().startswith("The agent's todo list as it stands:")
    s.todos.clear()
    assert s.todo_carry() == ""


def test_the_summary_fences_a_list_written_after_untrusted_reading(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.permissions.taint.sources.append("web_fetch u")
    todo_request(s, ["a"])
    assert "<untrusted" in s.todo_carry()


# --- chats: resume and rewind -----------------------------------------------------------------------------------------

def test_a_resumed_chat_has_its_list_back(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, save_chats=True)
    todo_request(s, [{"content": "a", "status": "completed"}, {"content": "b", "status": "in_progress"}], final="working")
    s.close()
    again = make_session(tmp_path, monkeypatch, save_chats=True)
    again.resume(again.chats()[0])
    assert [(i.content, i.status) for i in again.todos.items] == [("a", "completed"), ("b", "in_progress")]
    assert replay(again.chat.path).messages and "/todo" and run(again, "/todo").startswith("todo list (1 of 2 done)")


def test_a_resumed_chat_that_had_read_untrusted_content_brings_a_marked_list(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, save_chats=True)
    s.permissions.taint.sources.append("web_fetch http://example.com")
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("p", "todo_write", {"todos": ["a"]})), text("ok")] + [text("ok")] * 2)
    s.agent.add(Message("tool", '<untrusted source="web_fetch http://example.com">x</untrusted>', tool_call_id="old", tool_name="web_fetch"))
    s.agent.run("go")
    s.close()
    again = make_session(tmp_path, monkeypatch, save_chats=True)
    again.resume(again.chats()[0])
    assert again.todos.tainted


def test_rewinding_the_conversation_takes_the_list_back_to_what_it_was(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, file_history=True)
    todo_request(s, [{"content": "a", "status": "in_progress"}], final="first")
    s.todos.clear()                                                              # (as a new request would after a finished list)
    s.agent.provider = ScriptedProvider([write_call("9", {"content": "later", "status": "in_progress"}), text("second")] + [text("second")] * 2)
    s.agent.run("second request")
    assert [i.content for i in s.todos.items] == ["later"]
    run(s, "/rewind 2 chat")
    assert [i.content for i in s.todos.items] == ["a"]
    run(s, "/rewind 1 chat")
    assert s.todos.items == []


# --- showing it ---------------------------------------------------------------------------------------------------------------

def test_the_terminal_says_when_it_sends_the_model_back(capsys):
    PlainUI()("nudge", "[Note from the harness: ...]")
    assert "unfinished items" in capsys.readouterr().out


def test_the_whole_checklist_is_shown_not_cut_short(capsys):
    result = "Todo list updated (0 of 8 done):\n" + "\n".join(f"[ ] {n}. a step with some words in it to make the line long {n}" for n in range(1, 9))
    PlainUI()("tool_result", (ToolCall("1", "todo_write", {}), result))
    out = capsys.readouterr().out
    assert "8. a step" in out
    PlainUI()("tool_result", (ToolCall("2", "read_file", {}), result))
    assert "…" in capsys.readouterr().out


def test_the_setting_is_a_boolean_a_project_may_choose(tmp_path, monkeypatch):
    from harness.config import ConfigError, load_settings
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    (root / ".harness").mkdir(parents=True)
    (root / ".harness" / "settings.json").write_text(json.dumps({"todo": False}), encoding="utf-8")
    settings, warnings = load_settings(root)
    assert settings.todo is False and not warnings
    (root / ".harness" / "settings.json").write_text(json.dumps({"todo": "no"}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(root)


def test_the_approver_is_unused_for_the_todo_tool():
    assert PlainApprover is not None            # the real approver isn't involved: read-only tools never reach it


# --- a numbered request becomes the list (the harness writes it) ------------------------------------------------------------

from harness.todo import SEED_MIN, numbered_items  # noqa: E402

REQUEST = "Please do all of these:\n1. Fix the subtotal bug.\n2. Add a test for quantity 0.\n3) Update the README.\nThanks!"


def test_three_numbered_lines_are_a_list_with_the_first_in_progress():
    got = numbered_items(REQUEST)
    assert [(i.content, i.status) for i in got] == [("Fix the subtotal bug.", "in_progress"), ("Add a test for quantity 0.", "pending"), ("Update the README.", "pending")]


def test_fewer_than_three_numbered_lines_or_prose_numbers_are_not_a_list():
    assert numbered_items("1. one\n2. two") == [] and SEED_MIN == 3
    assert numbered_items("In 2024 we made 3. things happen, 2. times\nand 1. more") == []
    assert numbered_items("no numbers at all") == []
    assert len(numbered_items("\n".join(f"{n}. step {n}" for n in range(1, 40)))) == 20


def test_numbered_lines_indented_as_code_are_not_a_list():
    assert numbered_items("    1. a\n    2. b\n    3. c") == []


def test_a_numbered_request_starts_the_list_and_the_model_is_told(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = ScriptedProvider([text("ok")] * 3)
    s.agent.run(REQUEST)
    assert [i.content for i in s.todos.items] == ["Fix the subtotal bug.", "Add a test for quantity 0.", "Update the README."] and not s.todos.tainted
    sent = s.agent.messages[1].content
    assert sent.startswith(REQUEST) and "[Note from the harness: I made your todo list from the numbered items above:" in sent and "[~] 1. Fix the subtotal bug." in sent
    assert [d for k, d in s.ui.events if k == "todos"][0][0] == {"content": "Fix the subtotal bug.", "status": "in_progress"}


def test_the_seeded_list_is_nudged_like_any_other(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = ScriptedProvider([text("All done!"), write_call("w", *[{"content": c, "status": "completed"} for c in ("a", "b", "c")]), text("really")])
    assert s.agent.run(REQUEST) == "really" and s.agent.nudges == 1


def test_a_request_without_a_numbered_list_leaves_the_list_alone(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = ScriptedProvider([text("ok")])
    s.agent.run("just a question")
    assert s.todos.items == [] and s.agent.messages[1].content == "just a question"


def test_a_list_still_in_progress_is_not_replaced_by_a_new_request(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.todos.items = items(("old", "in_progress"))
    s.agent.provider = ScriptedProvider([text("ok")] * 3)
    s.agent.run(REQUEST)
    assert [i.content for i in s.todos.items] == ["old"] and "todo list from the numbered items" not in s.agent.messages[1].content


def test_a_finished_list_is_replaced_by_the_next_numbered_request(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.todos.items = items(("old", "completed"))
    s.agent.provider = ScriptedProvider([text("ok")] * 3)
    s.agent.run(REQUEST)
    assert len(s.todos.items) == 3 and s.todos.items[0].content == "Fix the subtotal bug."


def test_no_list_is_made_when_the_todo_setting_is_off(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, todo=False)
    s.agent.provider = ScriptedProvider([text("ok")])
    s.agent.run(REQUEST)
    assert s.todos.items == [] and s.agent.messages[1].content == REQUEST


def test_a_sub_agent_gets_no_list_made_for_it(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.provider.inner = ScriptedProvider([tool_calls(ToolCall("d", "delegate", {"agent": "explore", "task": REQUEST})), text("done"), text("ok")])
    s.agent.run("go")
    assert s.todos.items == []
