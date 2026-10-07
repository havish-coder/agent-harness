"""Lesson 40: chats saved as append-only logs, and rebuilt from them."""
import json
import os
import time

import pytest

from harness import config
from harness.chats import (
    Chat,
    ChatStore,
    ago,
    incomplete_tail,
    project_id,
    recap,
    replay,
    scan,
    title_from,
)
from harness.cli import choose_chat, parse_args
from harness.commands import load_commands
from harness.config import Settings
from harness.context.compact import SUMMARIZER_SYSTEM
from harness.context.micro import is_stub, make_stub
from harness.messages import Message, Reply, ToolCall, Usage, message_to_dict
from harness.providers.base import ProviderError
from harness.providers.fake import text, tool_calls
from harness.session import Session
from harness.tui.plain import PlainApprover, PlainUI
from harness.workspace import Workspace

# --- helpers --------------------------------------------------------------------------------


class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.warnings = []
        self.infos = []

    def __call__(self, kind, data):
        pass

    def warn(self, text_):
        self.warnings.append(text_)

    def info(self, text_):
        self.infos.append(text_)


def make_session(tmp_path, monkeypatch, name="work", **settings):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / name
    root.mkdir(exist_ok=True)
    for n in range(6):
        if not (root / f"part{n}.txt").exists():
            rows = [f"row {i:03}: value {(i * 7919 + n * 104729) % 100000:05} status ok" for i in range(130)]
            (root / f"part{n}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    s = Session(Settings(**settings), Workspace(root), Quiet(), PlainApprover())
    s.agent.stream = False
    return s


def logged(session):
    return [message_to_dict(m) for m in replay(session.chat.path).messages]


def live(session):
    return [message_to_dict(m) for m in session.agent.messages[1:]]


def read(n):
    return tool_calls(ToolCall(f"r{n}", "read_file", {"path": f"part{n}.txt"}))


def noting_read(n):
    return Reply(Message("assistant", f"noted part{n}", tool_calls=[ToolCall(f"r{n}", "read_file", {"path": f"part{n}.txt"})]),
                 "tool_calls", Usage())


class Script:
    """A provider that answers summary requests itself, so a scenario needn't count them."""

    model = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, tools):
        if messages[0].content == SUMMARIZER_SYSTEM:
            return text("Request: read.\nDone: read some files.")
        if not self.replies:
            raise ProviderError("script ran out")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def write_log(path, *entries, raw=()):
    lines = [json.dumps({"t": "chat", "v": 1, "id": path.stem, "created": "2026-01-01T00:00:00+00:00", "model": "m", "parent": None})]
    lines += [json.dumps(e) for e in entries] + list(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def msg(m):
    return {"t": "message", "at": "x", "m": message_to_dict(m)}


# --- names ----------------------------------------------------------------------------------

def test_a_project_has_a_readable_stable_name_that_differs_by_folder(tmp_path):
    a, b = tmp_path / "one" / "app", tmp_path / "two" / "app"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert project_id(a) == project_id(a) and project_id(a).startswith("app-") and project_id(a) != project_id(b)
    assert project_id(tmp_path / "My Project!").startswith("my-project-")


def test_titles_come_from_the_first_line_and_are_short():
    assert title_from("\n  fix the cart bug  \nplease") == "fix the cart bug"
    assert len(title_from("word " * 50)) <= 60 and title_from("word " * 50).endswith("…") and title_from("") == ""


def test_ages_are_rounded_for_reading():
    assert ago(30) == "just now" and ago(600) == "10 min ago" and ago(3 * 3600) == "3 h ago" and ago(5 * 86400) == "5 d ago"


# --- the log --------------------------------------------------------------------------------

def test_nothing_is_written_until_a_message_is(tmp_path):
    store = ChatStore(tmp_path / "home", tmp_path)
    chat = store.new("qwen")
    assert not chat.path.exists() and store.infos() == []
    chat.message(Message.user("hello"))
    first, second = chat.path.read_text(encoding="utf-8").splitlines()
    assert json.loads(first)["t"] == "chat" and json.loads(first)["model"] == "qwen" and json.loads(second)["t"] == "message"
    assert first.startswith('{"t":"chat"') and second.startswith('{"t":"message"')          # compact lines: the listing relies on it


def test_secrets_are_hidden_before_they_are_written(tmp_path):
    store = ChatStore(tmp_path / "home", tmp_path)
    chat = store.new("m")
    key = "sk-" + "a1b2c3d4e5f6" * 4
    chat.message(Message.user(f"my key is {key}"))
    chat.message(Message("assistant", "", tool_calls=[ToolCall("1", "run_shell", {"command": f"export TOKEN={key}"})]))
    text_on_disk = chat.path.read_text(encoding="utf-8")
    assert key not in text_on_disk and "[redacted" in text_on_disk.lower()


@pytest.mark.skipif(os.name == "nt", reason="file modes are not meaningful on Windows")
def test_chat_files_are_private_to_the_user(tmp_path):
    chat = ChatStore(tmp_path / "home", tmp_path).new("m")
    chat.message(Message.user("hi"))
    assert oct(chat.path.stat().st_mode & 0o777) == "0o600" and oct(chat.path.parent.stat().st_mode & 0o777) == "0o700"


# --- replay ---------------------------------------------------------------------------------

def test_messages_come_back_in_order_with_a_title(tmp_path):
    path = tmp_path / "c.jsonl"
    write_log(path, msg(Message.user("fix the cart")), msg(Message("assistant", "ok")), {"t": "title", "title": "Cart"})
    got = replay(path)
    assert [m.content for m in got.messages] == ["fix the cart", "ok"] and got.title == "Cart" and got.header["id"] == "c"


def test_without_a_title_entry_the_first_request_names_the_chat(tmp_path):
    path = tmp_path / "c.jsonl"
    write_log(path, msg(Message.user("fix the cart bug\nmore detail")), msg(Message("assistant", "ok")))
    assert replay(path).title == "fix the cart bug"


def test_a_later_title_wins(tmp_path):
    path = tmp_path / "c.jsonl"
    write_log(path, {"t": "title", "title": "first"}, msg(Message.user("x")), {"t": "title", "title": "second"})
    assert replay(path).title == "second"


def test_a_clear_entry_gives_the_same_note_the_agent_made(tmp_path):
    call = ToolCall("c1", "read_file", {"path": "a.py"})
    big = Message.tool_result(call, "line\n" * 800)
    path = tmp_path / "c.jsonl"
    write_log(path, msg(Message.user("go")), msg(Message("assistant", "", tool_calls=[call])), msg(big), {"t": "clear", "ids": ["c1"]})
    got = replay(path)
    assert is_stub(got.messages[2]) and got.messages[2].content == make_stub(call, big)
    assert (got.messages[2].tool_call_id, got.messages[2].tool_name) == ("c1", "read_file")


def test_a_compact_entry_replaces_the_first_messages_and_keeps_them_in_the_archive(tmp_path):
    summary = Message.user("[Summary of the earlier conversation, written when the window filled. Older messages were removed.]\n\nDone: x")
    path = tmp_path / "c.jsonl"
    write_log(path, msg(Message.user("one")), msg(Message("assistant", "two")), msg(Message.user("three")), msg(Message("assistant", "four")),
              {"t": "compact", "replaced": 2, "summary": message_to_dict(summary)})
    got = replay(path)
    assert [m.content for m in got.archive] == ["one", "two"] and got.compactions == 1
    assert got.messages[0].content == summary.content and [m.content for m in got.messages[1:]] == ["three", "four"]


def test_a_rollback_entry_removes_the_failed_turn(tmp_path):
    path = tmp_path / "c.jsonl"
    write_log(path, msg(Message.user("one")), msg(Message("assistant", "two")), msg(Message.user("three")), {"t": "rollback", "length": 2})
    assert [m.content for m in replay(path).messages] == ["one", "two"]


def test_a_crash_cuts_the_last_line_and_replay_skips_it(tmp_path):
    path = tmp_path / "c.jsonl"
    write_log(path, msg(Message.user("one")), msg(Message("assistant", "two")), raw=['{"t":"message","at":"x","m":{"role":"assista'])
    got = replay(path)
    assert [m.content for m in got.messages] == ["one", "two"] and got.damaged == 1


def test_lines_that_say_something_impossible_are_counted_not_fatal(tmp_path):
    path = tmp_path / "c.jsonl"
    write_log(path, msg(Message.user("one")), {"t": "compact"}, {"t": "rollback", "length": "many"}, {"t": "from the future", "x": 1},
              raw=["not json at all", "[1, 2]"])
    got = replay(path)
    assert [m.content for m in got.messages] == ["one"] and got.damaged == 4        # unknown kinds are ignored, not damage


def test_an_unfinished_tool_exchange_at_the_end_is_dropped(tmp_path):
    a = ToolCall("a", "read_file", {"path": "x"})
    b = ToolCall("b", "grep", {"pattern": "y"})
    path = tmp_path / "c.jsonl"
    write_log(path, msg(Message.user("go")), msg(Message("assistant", "", tool_calls=[a, b])), msg(Message.tool_result(a, "result of a")))
    got = replay(path)
    assert [m.role for m in got.messages] == ["user"] and got.dropped == 2          # b never got its result


def test_a_finished_exchange_is_kept():
    a = ToolCall("a", "read_file", {})
    view = [Message.user("go"), Message("assistant", "", tool_calls=[a]), Message.tool_result(a, "r")]
    assert incomplete_tail(view) == 3 and incomplete_tail([Message.user("hi")]) == 1


def test_fenced_text_in_a_chat_is_found_again(tmp_path):
    call = ToolCall("c", "web_fetch", {"url": "https://example.com"})
    page = Message.tool_result(call, '<untrusted source="web_fetch https://example.com">\nhello\n</untrusted>')
    summary = Message.user('[Summary of the earlier conversation, written when the window filled.]\n<untrusted source="summary of earlier steps">\nx\n</untrusted>')
    path = tmp_path / "c.jsonl"
    write_log(path, msg(Message.user("go")), msg(Message("assistant", "", tool_calls=[call])), msg(page), msg(summary))
    assert replay(path).untrusted == ["web_fetch https://example.com", "summary of earlier steps"]


def test_replaying_a_log_with_nothing_in_it_is_empty(tmp_path):
    path = tmp_path / "c.jsonl"
    write_log(path)
    got = replay(path)
    assert got.messages == [] and got.title == "" and got.damaged == 0


# --- the store ------------------------------------------------------------------------------

def fill(store, title, messages=2, age=0.0, parent=None):
    chat = store.new("m", parent=parent)
    chat.rename(title)
    for i in range(messages):
        chat.message(Message.user(f"{title} {i}"))
    if age:
        old = time.time() - age
        os.utime(chat.path, (old, old))
    return chat


def test_chats_are_listed_newest_first_with_what_the_list_shows(tmp_path):
    store = ChatStore(tmp_path / "home", tmp_path)
    old = fill(store, "old one", 3, age=3 * 86_400)
    new = fill(store, "new one", 5)
    infos = store.infos()
    assert [i.id for i in infos] == [new.id, old.id]
    assert (infos[0].title, infos[0].messages, infos[0].model) == ("new one", 5, "m") and infos[1].messages == 3
    assert infos[1].age().endswith("d ago") and scan(tmp_path / "nowhere.jsonl") is None


def test_a_chat_is_found_by_number_id_or_title(tmp_path):
    store = ChatStore(tmp_path / "home", tmp_path)
    cart = fill(store, "fix the cart", age=100)
    fill(store, "write the docs")
    assert store.find("2").id == cart.id and store.find(cart.id).id == cart.id and store.find("CART").id == cart.id
    assert store.find("the") is None                      # two titles contain it: not one chat
    assert store.find("9") is None and store.find("") is None and store.find("nothing like it") is None


def test_the_latest_chat_is_the_one_used_last(tmp_path):
    store = ChatStore(tmp_path / "home", tmp_path)
    assert store.latest() is None
    fill(store, "first", age=500)
    second = fill(store, "second")
    assert store.latest().id == second.id


def test_old_chats_are_deleted_and_the_open_one_is_not(tmp_path):
    store = ChatStore(tmp_path / "home", tmp_path)
    old = fill(store, "old", age=40 * 86_400)
    keep = fill(store, "also old", age=45 * 86_400)
    fresh = fill(store, "fresh")
    assert store.cleanup(30, keep={keep.id}) == 1
    assert not old.path.exists() and keep.path.exists() and fresh.path.exists()
    assert store.cleanup(0) == 0 and keep.path.exists()


def test_a_fork_starts_as_a_copy_and_remembers_its_parent(tmp_path):
    store = ChatStore(tmp_path / "home", tmp_path)
    chat = fill(store, "original", 4)
    copy = store.fork(chat, "m2", "original (fork)")
    a, b = replay(chat.path), replay(copy.path)
    assert [message_to_dict(m) for m in a.messages] == [message_to_dict(m) for m in b.messages]
    assert b.header["parent"] == chat.id and b.header["model"] == "m2" and b.title == "original (fork)" and a.title == "original"
    copy.message(Message.user("only in the copy"))
    assert len(replay(chat.path).messages) == 4 and len(replay(copy.path).messages) == 5
    assert store.find("fork").parent == chat.id


def test_projects_are_listed_once_they_have_been_used(tmp_path):
    home = tmp_path / "home"
    ChatStore(home, tmp_path / "a").register()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    ChatStore(home, tmp_path / "b").register()
    names = [p["name"] for p in ChatStore.projects(home)]
    assert sorted(names) == ["a", "b"] and all(p["id"].startswith(p["name"]) for p in ChatStore.projects(home))
    assert ChatStore.projects(tmp_path / "empty") == []


def test_a_recap_shows_the_last_request_and_answer():
    view = [Message.user("first"), Message("assistant", "one"), Message.user("second " * 80), Message("assistant", "two")]
    lines = recap(view).splitlines()
    assert lines[0].startswith("you:   second") and lines[0].endswith("…") and lines[1] == "agent: two" and recap([]) == ""


# --- a saved chat equals the live conversation ---------------------------------------------

def test_a_chat_with_tool_calls_is_saved_as_it_happens(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = Script([read(0), text("it has rows")])
    s.agent.run("what is in part0.txt?")
    assert s.chat is not None and s.chat.title == "what is in part0.txt?"
    assert logged(s) == live(s) and [m["role"] for m in logged(s)] == ["user", "assistant", "tool", "assistant"]


def test_old_results_cleared_during_a_chat_are_cleared_again_on_replay(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = Script([*[noting_read(n) for n in range(5)], text("done")])
    s.agent.run("read them")
    assert s.agent.cleared_results >= 3 and any(is_stub(m) for m in s.agent.messages)
    assert logged(s) == live(s)


def test_a_conversation_that_was_summarised_is_replayed_as_summarised(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = Script([read(n) for n in range(5)] + [text("done")])
    s.agent.run("read them")
    assert s.agent.compactions >= 1
    got = replay(s.chat.path)
    assert logged(s) == live(s) and got.compactions == s.agent.compactions and len(got.archive) == len(s.agent.archive)


def test_a_turn_that_failed_is_undone_in_the_log_too(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = Script([text("fine")])
    s.agent.run("first")
    s.agent.provider = Script([read(0), ProviderError("the model went away")])
    with pytest.raises(ProviderError):
        s.agent.run("second")
    assert [m["content"] for m in live(s)] == ["first", "fine"] and logged(s) == live(s)


def test_every_message_is_on_disk_before_the_next_model_call(tmp_path, monkeypatch):
    """So that closing the terminal in the middle of a task loses at most the step that was running."""
    s = make_session(tmp_path, monkeypatch)
    agreed = []

    class Watching(Script):
        def chat(self, messages, tools):
            if s.chat is not None:
                agreed.append(logged(s) == live(s))          # what the model is about to be sent is already in the log
            return super().chat(messages, tools)
    s.agent.provider = Watching([read(0), read(1), text("done")])
    s.agent.run("read two")
    assert len(agreed) >= 3 and all(agreed)


# --- the session ----------------------------------------------------------------------------

def test_a_chat_exists_only_once_a_message_is_sent(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert s.chat is None and s.chats() == []
    s.agent.provider = Script([text("hi")])
    s.agent.run("hello")
    assert len(s.chats()) == 1 and s.chats()[0].title == "hello" and s.chats()[0].messages == 2
    assert ChatStore.projects(tmp_path / "home")[0]["name"] == "work"


def test_nothing_is_saved_when_saving_is_off(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, save_chats=False)
    s.agent.provider = Script([text("hi")])
    s.agent.run("hello")
    assert s.store is None and s.chat is None and not (tmp_path / "home" / "projects").exists()
    assert "aren't being saved" in load_commands(s.ws.root).parse("/chats")[0].run(s, "")


def test_a_chat_that_cannot_be_saved_does_not_stop_the_agent(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    (tmp_path / "home" / "projects").mkdir(parents=True)
    s.store.dir.parent.rmdir()
    (tmp_path / "home" / "projects").write_text("a file where a folder should be", encoding="utf-8")
    s.agent.provider = Script([text("hi"), text("again")])
    assert s.agent.run("hello") == "hi" and s.agent.run("more") == "again"
    assert s.store is None and len([w for w in s.ui.warnings if "can't be saved" in w]) == 1


def test_a_new_chat_leaves_the_old_one_saved(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = Script([text("one"), text("two")])
    s.agent.run("first topic")
    old_path = s.chat.path
    reset = load_commands(s.ws.root).parse("/reset")[0].run(s, "")
    assert "saved" in reset and s.chat is None and len(s.agent.messages) == 1
    s.agent.run("second topic")
    assert s.chat.path != old_path and len(s.chats()) == 2 and len(replay(old_path).messages) == 2


def test_a_resumed_chat_goes_on_where_it_stopped(tmp_path, monkeypatch):
    first = make_session(tmp_path, monkeypatch)
    first.agent.provider = Script([read(0), text("it has rows")])
    first.agent.run("what is in part0.txt?")
    saved_live = live(first)
    second = make_session(tmp_path, monkeypatch)                       # a new process, the same project
    info = second.store.latest()
    got = second.resume(info)
    assert live(second) == saved_live and got.title == "what is in part0.txt?" and second.chat.id == info.id
    second.agent.provider = Script([text("the first file")])
    second.agent.run("which file was that?")
    assert [m["role"] for m in logged(second)][-2:] == ["user", "assistant"] and len(logged(second)) == len(saved_live) + 2
    assert len(second.chats()) == 1                                    # it went on in the same chat, not a new one


def test_a_resumed_chat_that_read_untrusted_content_is_still_tainted(tmp_path, monkeypatch):
    first = make_session(tmp_path, monkeypatch)
    first.agent.provider = Script([read(0), text("ok")])
    first.agent.run("read it")
    assert first.permissions.taint.active                              # the folder isn't trusted: its files are untrusted content
    second = make_session(tmp_path, monkeypatch)
    assert not second.permissions.taint.active
    got = second.resume(second.store.latest())
    assert second.permissions.taint.active and "read_file part0.txt" in second.permissions.taint.sources and got.untrusted


def test_resuming_a_chat_forgets_that_files_were_read(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = Script([read(0), text("ok")])
    s.agent.run("read it")
    s.resume(s.store.latest())
    read_tool = next(t for t in s.agent.tools if t.name == "read_file")
    assert "row 000" in s.agent.tools.invoke(read_tool, {"path": "part0.txt"})         # returns the text, not "unchanged"


def test_a_chat_cut_off_in_the_middle_of_a_step_is_repaired_and_the_file_agrees(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    call = ToolCall("x", "read_file", {"path": "part0.txt"})
    chat = s.store.new("m")
    chat.message(Message.user("go"))
    chat.message(Message("assistant", "", tool_calls=[call]))                          # the terminal closed before the result
    info = s.store.latest()
    got = s.resume(info)
    assert got.dropped == 1 and [m.role for m in s.agent.messages[1:]] == ["user"]
    assert [m.role for m in replay(info.path).messages] == ["user"] and replay(info.path).dropped == 0


def test_a_secret_typed_by_the_user_is_not_in_the_file_but_is_in_the_conversation(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    key = "sk-" + "z9y8x7w6v5u4" * 4
    s.agent.provider = Script([text("noted")])
    s.agent.run(f"use this key: {key}")
    assert key in s.agent.messages[1].content and key not in s.chat.path.read_text(encoding="utf-8")


def test_old_chats_are_removed_when_a_session_starts(tmp_path, monkeypatch):
    first = make_session(tmp_path, monkeypatch)
    old = fill(first.store, "ancient", age=50 * 86_400)
    again = make_session(tmp_path, monkeypatch)
    assert not old.path.exists() and again.chats() == []
    keep = make_session(tmp_path, monkeypatch, name="other", chat_retention_days=0)
    forever = fill(keep.store, "ancient", age=500 * 86_400)
    assert make_session(tmp_path, monkeypatch, name="other", chat_retention_days=0).chats()[0].id == forever.id


# --- the commands ---------------------------------------------------------------------------

def run(session, line):
    command, args = load_commands(session.ws.root).parse(line)
    return command.run(session, args)


def test_chats_lists_this_project_with_a_marker_on_the_open_one(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "no saved chats" in run(s, "/chats")
    fill(s.store, "an older chat", age=7200)
    s.agent.provider = Script([text("hi")])
    s.agent.run("current topic")
    out = run(s, "/chats").splitlines()
    assert out[0].startswith("saved chats in this project") and out[1].startswith("* ") and "current topic" in out[1]
    assert out[2].startswith("  ") and "an older chat" in out[2] and "2 h ago" in out[2]


def test_resume_goes_back_and_says_what_it_restored(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = Script([text("answer one"), text("answer two")])
    s.agent.run("topic one")
    run(s, "/reset")
    s.agent.run("topic two")
    out = run(s, "/resume 2")
    assert out.startswith("resumed: topic one (2 messages)") and "you:   topic one" in out and "agent: answer one" in out
    assert "reads a file again before editing" in out and [m.content for m in s.agent.messages[1:]] == ["topic one", "answer one"]


def test_resume_explains_a_wrong_reference(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert run(s, "/resume").startswith("usage:") and "no single chat matches 'zzz'" in run(s, "/resume zzz")


def test_resume_mentions_untrusted_reading_and_repairs(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = Script([read(0), text("ok")])
    s.agent.run("read it")
    run(s, "/reset")
    assert "may not trust" in run(s, "/resume 1")


def test_rename_names_the_chat_and_the_list_shows_it(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "send one first" in run(s, "/rename Cart work")
    s.agent.provider = Script([text("hi")])
    s.agent.run("hello")
    assert run(s, "/rename  Cart   work ") == "this chat is now called: Cart work" and "Cart work" in run(s, "/chats")
    assert run(s, "/rename").startswith("usage:")


def test_fork_carries_on_in_a_copy(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "nothing to fork" in run(s, "/fork")
    s.agent.provider = Script([text("hi"), text("in the fork")])
    s.agent.run("hello")
    original = s.chat.path
    assert "forked: you are now in 'hello (fork)'" in run(s, "/fork")
    s.agent.run("only here")
    assert len(replay(original).messages) == 2 and len(replay(s.chat.path).messages) == 4
    assert len(s.chats()) == 2 and "fork" in run(s, "/chats")
    assert "'try it'" in run(s, "/fork try it")


# --- the command line -----------------------------------------------------------------------

def test_the_flags_for_resuming_and_not_saving():
    assert parse_args([]).continue_chat is False and parse_args([]).resume is None and parse_args([]).no_save is False
    assert parse_args(["-c"]).continue_chat and parse_args(["--continue"]).continue_chat
    assert parse_args(["-r", "cart"]).resume == "cart" and parse_args(["--resume"]).resume == "" and parse_args(["--no-save"]).no_save


def test_start_up_picks_the_chat_the_user_asked_for(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    ui = s.ui
    assert choose_chat(s, None, True, ui) is None and "no earlier chat" in ui.infos[-1]
    fill(s.store, "fix the cart", age=60)
    newest = fill(s.store, "write the docs")
    assert choose_chat(s, None, True, ui).id == newest.id
    assert choose_chat(s, "cart", False, ui).title == "fix the cart"
    assert choose_chat(s, "zzz", False, ui) is None and "starts a new one" in ui.warnings[-1].replace("starting a new one", "starts a new one")


def test_start_up_can_offer_a_list(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    fill(s.store, "fix the cart", age=60)
    fill(s.store, "write the docs")
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    assert choose_chat(s, "", False, s.ui).title == "fix the cart" and any("write the docs" in i for i in s.ui.infos)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert choose_chat(s, "", False, s.ui) is None


def test_start_up_with_saving_off_says_so(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, save_chats=False)
    assert choose_chat(s, None, True, s.ui) is None and "nothing to resume" in s.ui.warnings[-1]


def test_a_chat_object_survives_being_reopened(tmp_path):
    store = ChatStore(tmp_path / "home", tmp_path)
    chat = fill(store, "first", 2)
    again = store.open(store.infos()[0])
    assert isinstance(again, Chat) and again.id == chat.id and again.path == chat.path
    again.message(Message.user("more"))
    assert store.infos()[0].messages == 3
