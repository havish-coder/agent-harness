"""Lesson 43: file history, /undo and /rewind. What the agent changed, put back."""
import json
import os
import time

import pytest

from harness import config
from harness import filehistory as fh
from harness.chats import replay
from harness.commands import load_commands
from harness.config import ConfigError, Settings, load_settings
from harness.filehistory import FileHistory, clean_name, digest, line_counts, listing, outcome_text, parse_log
from harness.messages import Message, ToolCall, message_from_dict, message_to_dict
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.session import Session
from harness.tools.edit import EditError, make_edit_tools
from harness.tui.plain import PlainApprover, PlainUI
from harness.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    return Workspace(root)


@pytest.fixture
def hist(tmp_path, ws):
    return FileHistory(tmp_path / "hist", ws)


def put(ws, hist, rel, content, tool="edit_file"):
    """What an edit tool does: hand the old bytes to the history, then write."""
    p = ws.path(rel)
    before = p.read_bytes() if p.exists() else None
    data = content if isinstance(content, bytes) else content.encode()
    made = []
    for d in (p.parent, *p.parent.parents):
        if d.exists():
            break
        made.append(d)
    hist.record(p, before, data, tool, made)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def read(ws, rel):
    return ws.path(rel).read_bytes()


def undo_last(hist, force=False):
    turn = hist.pending_turns()[-1]
    return hist.apply(hist.plan([turn]), force)


# --- recording and putting back ---------------------------------------------------------------------------

def test_a_changed_file_is_put_back_exactly(ws, hist):
    (ws.root / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    hist.begin_turn("t1", "change a")
    put(ws, hist, "a.txt", "one\r\nTWO\r\n")
    out = undo_last(hist)
    assert out.restored == ["a.txt"] and read(ws, "a.txt") == b"one\r\ntwo\r\n"          # even the line endings


def test_binary_and_unicode_content_survives(ws, hist):
    raw = bytes(range(256)) + "héllo ✓".encode()
    (ws.root / "b.bin").write_bytes(raw)
    hist.begin_turn("t1", "x")
    put(ws, hist, "b.bin", b"other")
    undo_last(hist)
    assert read(ws, "b.bin") == raw


def test_a_new_file_is_removed_and_the_folders_it_made_with_it(ws, hist):
    hist.begin_turn("t1", "make files")
    put(ws, hist, "pkg/sub/new.py", "x = 1\n", "write_file")
    assert (ws.root / "pkg" / "sub" / "new.py").exists()
    out = undo_last(hist)
    assert out.deleted == ["pkg/sub/new.py"] and not (ws.root / "pkg").exists()


def test_a_folder_two_requests_wrote_into_goes_when_both_are_undone(ws, hist):
    """Found by scripts/history_lab.py: 52 of 300 random chats left the empty folders behind."""
    hist.begin_turn("t1", "first")
    put(ws, hist, "d/sub/one.txt", "1", "write_file")
    hist.begin_turn("t2", "second")
    put(ws, hist, "d/sub/two.txt", "2", "write_file")
    out = hist.apply(hist.plan(hist.pending_turns()))
    assert sorted(out.deleted) == ["d/sub/one.txt", "d/sub/two.txt"] and not (ws.root / "d").exists()


def test_undoing_only_the_later_request_keeps_the_folder_the_earlier_one_made(ws, hist):
    hist.begin_turn("t1", "first")
    put(ws, hist, "d/one.txt", "1", "write_file")
    hist.begin_turn("t2", "second")
    put(ws, hist, "d/two.txt", "2", "write_file")
    undo_last(hist)
    assert (ws.root / "d" / "one.txt").exists() and not (ws.root / "d" / "two.txt").exists()


def test_a_folder_that_has_something_else_in_it_stays(ws, hist):
    hist.begin_turn("t1", "make a file")
    put(ws, hist, "pkg/new.py", "x = 1\n", "write_file")
    (ws.root / "pkg" / "mine.txt").write_text("mine", encoding="utf-8")
    undo_last(hist)
    assert not (ws.root / "pkg" / "new.py").exists() and (ws.root / "pkg" / "mine.txt").exists()


def test_several_changes_to_one_file_in_a_request_put_back_the_first_state(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.begin_turn("t1", "three edits")
    for v in ("v1", "v2", "v3"):
        put(ws, hist, "a.txt", v)
    turn = hist.pending_turns()[0]
    assert len(turn.edits) == 1 and turn.edits["a.txt"].before == digest(b"v0") and turn.edits["a.txt"].after == digest(b"v3")
    undo_last(hist)
    assert read(ws, "a.txt") == b"v0"


def test_undo_goes_back_one_request_at_a_time(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.begin_turn("t1", "first")
    put(ws, hist, "a.txt", "v1")
    hist.begin_turn("t2", "second")
    put(ws, hist, "a.txt", "v2")
    undo_last(hist)
    assert read(ws, "a.txt") == b"v1"
    undo_last(hist)
    assert read(ws, "a.txt") == b"v0" and hist.pending_turns() == []


def test_putting_back_two_requests_at_once_uses_the_oldest_state(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.begin_turn("t1", "first")
    put(ws, hist, "a.txt", "v1")
    hist.begin_turn("t2", "second")
    put(ws, hist, "a.txt", "v2")
    out = hist.apply(hist.plan(hist.pending_turns()))
    assert out.restored == ["a.txt"] and read(ws, "a.txt") == b"v0"


def test_the_same_request_can_be_undone_only_once(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "v1")
    undo_last(hist)
    assert hist.pending_turns() == []


# --- not destroying your own work -------------------------------------------------------------------------

def test_a_file_you_edited_since_is_left_alone(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "agent")
    (ws.root / "a.txt").write_text("mine", encoding="utf-8")                      # the user edits it afterwards
    out = undo_last(hist)
    assert out.skipped == [("a.txt", "has changed since the agent wrote it")] and read(ws, "a.txt") == b"mine"
    assert "SKIPPED a.txt" in outcome_text(out) and "force" in outcome_text(out)
    assert len(hist.pending_turns()) == 1                                           # still there to undo later


def test_force_overwrites_but_keeps_your_version(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "agent")
    (ws.root / "a.txt").write_text("mine", encoding="utf-8")
    out = undo_last(hist, force=True)
    assert read(ws, "a.txt") == b"v0" and out.restored == ["a.txt"]
    assert hist.blob(out.kept["a.txt"]).read_bytes() == b"mine"                     # recoverable from the history folder


def test_a_file_you_deleted_since_is_not_brought_back_without_force(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "agent")
    (ws.root / "a.txt").unlink()
    out = undo_last(hist)
    assert out.skipped and "deleted since" in out.skipped[0][1] and not (ws.root / "a.txt").exists()
    assert undo_last(hist, force=True).restored == ["a.txt"] and read(ws, "a.txt") == b"v0"


def test_a_file_already_as_it_was_counts_as_done(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "agent")
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")                          # you put it back yourself
    out = undo_last(hist)
    assert out.same == ["a.txt"] and hist.pending_turns() == []


def test_a_new_file_you_changed_is_not_deleted(ws, hist):
    hist.begin_turn("t1", "x")
    put(ws, hist, "new.py", "agent", "write_file")
    (ws.root / "new.py").write_text("mine", encoding="utf-8")
    out = undo_last(hist)
    assert out.skipped and read(ws, "new.py") == b"mine"


def test_a_conflict_in_one_file_doesnt_stop_the_others(ws, hist):
    (ws.root / "a.txt").write_text("a0", encoding="utf-8")
    (ws.root / "b.txt").write_text("b0", encoding="utf-8")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "a1")
    put(ws, hist, "b.txt", "b1")
    (ws.root / "a.txt").write_text("mine", encoding="utf-8")
    out = undo_last(hist)
    assert out.restored == ["b.txt"] and [p for p, _ in out.skipped] == ["a.txt"]
    assert [e.path for e in hist.pending_turns()[0].pending()] == ["a.txt"]         # only the skipped one is left to do


def test_a_path_that_leaves_the_workspace_in_the_log_is_refused(tmp_path, ws, hist):
    outside = tmp_path / "outside.txt"
    outside.write_text("precious", encoding="utf-8")
    log = hist.base / "chat1.jsonl"
    hist.base.mkdir(parents=True)
    sha = hist.keep(b"planted")
    log.write_text("\n".join(json.dumps(e) for e in [
        {"t": "turn", "id": "t1", "prompt": "x"},
        {"t": "change", "turn": "t1", "path": "../outside.txt", "first": True, "before": sha, "after": digest(b"precious"), "plus": 1, "minus": 1},
    ]), encoding="utf-8")
    hist.bind("chat1")
    out = undo_last(hist, force=True)
    assert out.skipped and not out.restored and outside.read_text(encoding="utf-8") == "precious"


def test_a_missing_or_damaged_copy_is_an_error_for_that_file_only(ws, hist):
    (ws.root / "a.txt").write_text("a0", encoding="utf-8")
    (ws.root / "b.txt").write_text("b0", encoding="utf-8")
    (ws.root / "c.txt").write_text("c0", encoding="utf-8")
    hist.begin_turn("t1", "x")
    for name in "abc":
        put(ws, hist, f"{name}.txt", f"{name}1")
    hist.blob(digest(b"a0")).unlink()                                               # lost
    hist.blob(digest(b"b0")).write_bytes(b"tampered")                               # damaged
    out = undo_last(hist)
    assert out.restored == ["c.txt"] and {p for p, _ in out.errors} == {"a.txt", "b.txt"}
    assert read(ws, "a.txt") == b"a1" and read(ws, "b.txt") == b"b1"                # never replaced by a bad copy


def test_no_temporary_files_are_left_behind(ws, hist):
    (ws.root / "a.txt").write_text("a0", encoding="utf-8")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "a1")
    undo_last(hist)
    assert sorted(p.name for p in ws.root.iterdir()) == ["a.txt"]


# --- the log ---------------------------------------------------------------------------------------------

def test_the_log_rebuilds_what_happened(tmp_path, ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.bind("c1")
    hist.begin_turn("t1", "first request")
    put(ws, hist, "a.txt", "v1")
    put(ws, hist, "new.py", "x\ny\n", "write_file")
    hist.note_command("python make.py")
    hist.begin_turn("t2", "second")
    put(ws, hist, "a.txt", "v2")
    again = FileHistory(hist.base, ws)
    again.bind("c1")
    assert [t.id for t in again.all] == ["t1", "t2"]
    t1 = again.all[0]
    assert set(t1.edits) == {"a.txt", "new.py"} and t1.edits["new.py"].new and t1.commands == ["python make.py"]
    assert t1.edits["a.txt"].before == digest(b"v0") and t1.edits["a.txt"].after == digest(b"v1")
    undo_last(again)                                                                # a resumed chat can still undo
    assert read(ws, "a.txt") == b"v1"


def test_reverted_and_dropped_are_remembered(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.bind("c1")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "v1")
    undo_last(hist)
    hist.drop([hist.all[0]])
    again = FileHistory(hist.base, ws)
    again.bind("c1")
    assert again.all[0].dropped and again.pending_turns() == [] and again.listed() == []


def test_a_damaged_log_line_is_skipped(ws, hist):
    log = '{"t":"turn","id":"t1","prompt":"x"}\nnot json\n{"t":"change","turn":"nope","path":"a","first":true}\n{"t":"command","turn":"t1","text":"c"}\n'
    turns = parse_log(log)
    assert [t.id for t in turns] == ["t1"] and turns[0].commands == ["c"]


def test_the_prompt_is_kept_short_and_secrets_are_hidden(ws, hist):
    hist.begin_turn("t1", "use key sk-ant-api03-" + "a" * 40 + " " + "word " * 60)
    assert "sk-ant" not in hist.all[0].prompt and len(hist.all[0].prompt) <= fh.PROMPT_CHARS


def test_the_log_is_private_to_the_user_where_the_system_allows(tmp_path, ws, hist):
    hist.bind("c1")
    hist.begin_turn("t1", "x")
    if os.name != "nt":
        assert oct(hist.log.stat().st_mode & 0o777) == "0o600"
    assert hist.log.exists() and hist.base != ws.root and not hist.base.is_relative_to(ws.root)     # not in the workspace


def test_fork_gives_the_new_chat_the_same_history(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.bind("c1")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "v1")
    hist.fork_to("c2")
    undo_last(hist)                                                                 # undone in the fork
    original = FileHistory(hist.base, ws)
    original.bind("c1")
    assert len(original.pending_turns()) == 1                                       # the original's log is untouched
    assert hist.log.name == "c2.jsonl"


def test_unbind_starts_a_new_chat_with_nothing_to_undo(ws, hist):
    hist.bind("c1")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "v1")
    hist.unbind()
    assert hist.all == [] and hist.pending_turns() == [] and hist.chat_id is None


def test_sweep_removes_what_nothing_refers_to(ws, hist):
    (ws.root / "a.txt").write_text("v0", encoding="utf-8")
    hist.bind("live")
    hist.begin_turn("t1", "x")
    put(ws, hist, "a.txt", "v1")
    orphan = hist.keep(b"orphan content")
    old = time.time() - fh.BLOB_GRACE - 10
    os.utime(hist.blob(orphan), (old, old))
    fresh = hist.keep(b"fresh but unreferenced")                                    # too new: a log line may be on its way
    (hist.base / "gone.jsonl").write_text('{"t":"turn","id":"x","prompt":"y"}\n', encoding="utf-8")
    assert hist.sweep({"live"}) == 1
    assert not hist.blob(orphan).exists() and hist.blob(fresh).exists() and hist.blob(digest(b"v0")).exists()
    assert not (hist.base / "gone.jsonl").exists() and (hist.base / "live.jsonl").exists()


# --- when it can't keep a copy ----------------------------------------------------------------------------

def test_a_full_store_lets_the_edit_go_ahead_and_says_so_once(ws, tmp_path, monkeypatch):
    problems = []
    h = FileHistory(tmp_path / "hist", ws, on_problem=problems.append)
    monkeypatch.setattr(fh, "MAX_STORE_BYTES", 5)
    (ws.root / "a.txt").write_text("0123456789", encoding="utf-8")
    (ws.root / "b.txt").write_text("abcdefghij", encoding="utf-8")
    h.begin_turn("t1", "x")
    assert h.record(ws.path("a.txt"), b"0123456789", b"new", "edit_file") is False
    assert h.record(ws.path("b.txt"), b"abcdefghij", b"new", "edit_file") is False
    assert len(problems) == 2 and "history is full" in problems[0] and "a.txt" in problems[0]     # one per file, not per attempt
    assert h.pending_turns() == []


def test_a_file_too_big_for_a_copy_is_reported(ws, hist, monkeypatch):
    problems = []
    hist.on_problem = problems.append
    monkeypatch.setattr(fh, "MAX_FILE_BYTES", 10)
    hist.begin_turn("t1", "x")
    assert hist.record(ws.path("big.txt"), b"x" * 11, b"y", "edit_file") is False
    assert "too big" in problems[0]


def test_a_log_that_cant_be_written_is_reported_not_raised(ws, tmp_path):
    problems = []
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    h = FileHistory(blocker / "hist", ws, on_problem=problems.append)
    h.bind("c1")
    h.begin_turn("t1", "x")
    assert problems and "can't be written" in problems[0]


# --- counting, naming ----------------------------------------------------------------------------------------

def test_line_counts():
    assert line_counts(b"a\nb\nc\n", b"a\nB\nc\nd\n") == (2, 1)
    assert line_counts(None, b"x\ny\n") == (2, 0)
    assert line_counts(b"x\n" * 3000, b"y\n" * 3000) == (3000, 3000)               # large: counted roughly, not diffed


def test_names_are_cleaned_for_messages():
    assert clean_name("a\nb\x1b[31m.py") == "a b [31m.py" and len(clean_name("x" * 500)) == 120


def test_the_listing_shows_requests_and_files(ws, hist):
    (ws.root / "a.txt").write_text("v0\n", encoding="utf-8")
    hist.begin_turn("t1", "fix the bug")
    put(ws, hist, "a.txt", "v1\n")
    hist.begin_turn("t2", "just a question")
    hist.begin_turn("t3", "make files")
    put(ws, hist, "n.py", "x", "write_file")
    hist.note_command("make")
    rows = listing(hist)
    assert "  1  fix the bug" in rows and "a.txt (+1 -1)" in rows and "no file changes" in rows
    assert "n.py (new)" in rows and "ran 1 command that may have changed files" in rows


# --- the edit tools ----------------------------------------------------------------------------------------

def edit_tools(ws, hist):
    return {t.name: t for t in make_edit_tools(ws, hist)}


def mark_read(ws, rel):
    from harness.tools.fs import read_lines
    read_lines(ws, rel)


def test_edit_file_hands_over_the_exact_old_bytes(ws, hist):
    (ws.root / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    mark_read(ws, "a.txt")
    hist.begin_turn("t1", "x")
    edit_tools(ws, hist)["edit_file"].fn(path="a.txt", old_string="two", new_string="2")
    assert undo_last(hist).restored == ["a.txt"] and read(ws, "a.txt") == b"one\r\ntwo\r\n"


def test_write_file_over_a_file_and_to_a_new_one(ws, hist):
    (ws.root / "a.txt").write_text("old", encoding="utf-8")
    mark_read(ws, "a.txt")
    hist.begin_turn("t1", "x")
    tools = edit_tools(ws, hist)
    tools["write_file"].fn(path="a.txt", content="new")
    tools["write_file"].fn(path="d/e/f.txt", content="brand new")
    out = undo_last(hist)
    assert sorted(out.restored + out.deleted) == ["a.txt", "d/e/f.txt"] and read(ws, "a.txt") == b"old" and not (ws.root / "d").exists()


def test_an_edit_that_fails_leaves_no_history(ws, hist):
    (ws.root / "a.txt").write_text("one", encoding="utf-8")
    mark_read(ws, "a.txt")
    hist.begin_turn("t1", "x")
    with pytest.raises(EditError):
        edit_tools(ws, hist)["edit_file"].fn(path="a.txt", old_string="missing", new_string="x")
    assert hist.pending_turns() == []


def test_the_tools_work_without_a_history(ws):
    (ws.root / "a.txt").write_text("one", encoding="utf-8")
    mark_read(ws, "a.txt")
    result = edit_tools(ws, None)["edit_file"].fn(path="a.txt", old_string="one", new_string="two")
    assert result.startswith("Edited") and read(ws, "a.txt") == b"two"


def test_a_change_with_no_request_open_gets_a_turn_of_its_own(ws, hist):
    put(ws, hist, "a.txt", "x", "write_file")
    assert hist.all[0].id == "-" and hist.pending_turns()[0].prompt.startswith("(a change made outside")


# --- messages carry the request's id -----------------------------------------------------------------------

def test_a_checkpoint_survives_the_log_form_and_doesnt_affect_equality():
    m = Message.user("hi", checkpoint="abcd1234")
    assert message_from_dict(message_to_dict(m)).checkpoint == "abcd1234"
    assert "checkpoint" not in message_to_dict(Message.user("hi")) and m == Message.user("hi")


# --- the session ----------------------------------------------------------------------------------------------

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


def make_session(tmp_path, monkeypatch, files=None, **settings):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(content, encoding="utf-8")
    from harness.security.trust import set_trusted
    set_trusted(root, config.USER_DIR, True)
    base = {"save_chats": False, "auto_memory": "off", "journal": "off", "permission_mode": "bypass"}
    s = Session(Settings(**(base | settings)), Workspace(root), Quiet(), PlainApprover())
    s.agent.stream = False
    return s


def edits(s, *steps):
    """Run one request in which the model makes these (tool, args) calls."""
    replies = [tool_calls(*[ToolCall(f"c{i}", name, args) for i, (name, args) in enumerate(steps)]), text("done")]
    s.agent.provider = ScriptedProvider(replies)
    s.agent.run("request " + str(len(s.agent.messages)))


def read_file(path):
    return ("read_file", {"path": path})


def write(path, content):
    return ("write_file", {"path": path, "content": content})


def edit(path, old, new):
    return ("edit_file", {"path": path, "old_string": old, "new_string": new})


def run(session, line):
    command, args = load_commands(session.ws.root).parse(line)
    return command.run(session, args)


def test_a_request_is_a_turn_and_its_edit_is_undone_with_a_command(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    assert (s.ws.root / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert s.agent.messages[1].checkpoint and len(s.history.all) == 1
    said = run(s, "/undo")
    assert "undid" in said and "put back: a.txt" in said and (s.ws.root / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert run(s, "/undo") == "no file changes to undo"


def test_undo_show_changes_nothing(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    said = run(s, "/undo show")
    assert "put back" in said and "a.txt" in said and (s.ws.root / "a.txt").read_text(encoding="utf-8") == "two\n"


def test_undo_tells_the_model_with_its_next_request(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    run(s, "/undo")
    assert s.agent.pending_notes and "a.txt" in s.agent.pending_notes[0]
    s.agent.provider = ScriptedProvider([text("ok")])
    s.agent.run("go on")
    sent = s.agent.messages[-2].content
    assert sent.startswith("[Note from the harness:") and "a.txt" in sent and sent.endswith("go on") and s.agent.pending_notes == []


def test_undo_twice_goes_to_the_earlier_request(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "v0\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "v0", "v1"))
    edits(s, read_file("a.txt"), edit("a.txt", "v1", "v2"))
    run(s, "/undo")
    assert (s.ws.root / "a.txt").read_text(encoding="utf-8") == "v1\n"
    run(s, "/undo")
    assert (s.ws.root / "a.txt").read_text(encoding="utf-8") == "v0\n"


def test_undo_skips_what_you_changed_and_force_takes_it(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    (s.ws.root / "a.txt").write_text("mine\n", encoding="utf-8")
    assert "SKIPPED a.txt" in run(s, "/undo") and (s.ws.root / "a.txt").read_text(encoding="utf-8") == "mine\n"
    assert "kept" in run(s, "/undo force") and (s.ws.root / "a.txt").read_text(encoding="utf-8") == "one\n"


def test_a_shell_command_is_reported_as_not_undoable(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"), ("run_shell", {"command": "python -c \"open('gen.txt','w').write('x')\""}))
    said = run(s, "/undo")
    assert "shell command(s) ran" in said and "not undone" in said and (s.ws.root / "gen.txt").exists()


def test_nothing_to_undo_says_so_and_mentions_commands(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert run(s, "/undo") == "no file changes to undo"
    edits(s, ("run_shell", {"command": "python -c \"open('gen.txt','w').write('x')\""}))
    assert "1 shell command(s) ran" in run(s, "/undo")


def test_rewind_lists_the_requests(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    assert run(s, "/rewind") == "no requests yet in this chat"
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    edits(s, write("n.py", "x = 1\n"))
    said = run(s, "/rewind")
    assert "  1  request 1" in said and "  2  request" in said and "a.txt (+1 -1)" in said and "n.py (new)" in said and "/rewind N" in said


def test_rewind_both_restores_files_and_forgets_the_conversation(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    n = len(s.agent.messages)
    edits(s, write("n.py", "x = 1\n"))
    said = run(s, "/rewind 2")
    assert "rewound to before request 2" in said and not (s.ws.root / "n.py").exists()
    assert (s.ws.root / "a.txt").read_text(encoding="utf-8") == "two\n"             # request 1 is kept
    assert len(s.agent.messages) == n and [m.role for m in s.agent.messages].count("user") == 1
    assert len(s.history.listed()) == 1


def test_rewind_to_the_first_request_puts_everything_back(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    edits(s, write("n.py", "x = 1\n"))
    run(s, "/rewind 1")
    assert (s.ws.root / "a.txt").read_text(encoding="utf-8") == "one\n" and not (s.ws.root / "n.py").exists()
    assert len(s.agent.messages) == 1 and s.history.listed() == []                 # only the system prompt is left


def test_rewind_code_keeps_the_conversation_and_tells_the_model(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    n = len(s.agent.messages)
    run(s, "/rewind 1 code")
    assert len(s.agent.messages) == n and (s.ws.root / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert "a.txt" in s.agent.pending_notes[0] and "undid your file changes" in s.agent.pending_notes[0]
    assert [t.pending() for t in s.history.listed()] == [[]]                        # still listed, files put back
    assert "all put back" in run(s, "/rewind")


def test_rewind_chat_keeps_the_files_and_tells_the_model_which_changed(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    run(s, "/rewind 1 chat")
    assert len(s.agent.messages) == 1 and (s.ws.root / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert "still hold changes" in s.agent.pending_notes[0] and "a.txt" in s.agent.pending_notes[0]
    assert run(s, "/undo").startswith("undid")                                      # the files can still be undone


def test_rewind_show_changes_nothing(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    n = len(s.agent.messages)
    said = run(s, "/rewind 1 show")
    assert "would put these files back" in said and "a.txt" in said
    assert len(s.agent.messages) == n and (s.ws.root / "a.txt").read_text(encoding="utf-8") == "two\n" and not s.agent.pending_notes


def test_rewind_checks_its_arguments(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    assert "no request 9" in run(s, "/rewind 9")
    assert "usage" in run(s, "/rewind x") and "not 'sideways'" in run(s, "/rewind 1 sideways") and "not 'x'" in run(s, "/undo x")


def test_a_conflict_while_rewinding_is_reported_and_the_model_is_told(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    (s.ws.root / "a.txt").write_text("mine\n", encoding="utf-8")
    said = run(s, "/rewind 1")
    assert "SKIPPED a.txt" in said and len(s.agent.messages) == 1
    assert "still hold changes" in s.agent.pending_notes[-1]


def test_rewind_when_the_conversation_was_summarised_away(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    s.agent.messages[1:] = [Message.user("[Summary of earlier conversation] ...")]        # what compaction leaves
    said = run(s, "/rewind 1")
    assert "can't go back that far" in said and (s.ws.root / "a.txt").read_text(encoding="utf-8") == "one\n"      # the files still go back


def test_taint_stays_after_a_rewind(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    s.permissions.taint.sources.append("web_fetch http://example.com")
    assert s.permissions.taint.active
    run(s, "/rewind 1")
    assert s.permissions.taint.active                                                # forgetting a page doesn't make it safe


def test_the_model_has_no_undo_and_cannot_reach_the_history(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    names = [t["name"] for t in s.agent.tools.schemas()]
    assert names and not [n for n in names if "undo" in n or "rewind" in n or "history" in n]
    with pytest.raises(PermissionError):
        s.ws.path(str(s.history.base / "x.jsonl"))


def test_undo_makes_the_next_journal_update_say_the_work_is_gone(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    run(s, "/undo")
    assert s.unjournaled and "undid the file changes" in s.undo_focus and "request" in s.undo_focus


def test_file_history_off_keeps_nothing(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"}, file_history=False)
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    assert s.history is None and "off" in run(s, "/undo") and "off" in run(s, "/rewind") and (s.ws.root / "a.txt").read_text(encoding="utf-8") == "two\n"


def test_without_saved_chats_the_history_is_temporary(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    base = s.history.base
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    assert base.exists() and not base.is_relative_to(tmp_path / "home")
    run(s, "/undo")
    s.close()
    assert not base.exists()


def test_the_setting_is_checked_and_not_taken_from_a_project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    (root / ".harness").mkdir(parents=True)
    (root / ".harness" / "settings.json").write_text(json.dumps({"file_history": False}), encoding="utf-8")
    settings, warnings = load_settings(root)
    assert settings.file_history is True and any("can't set 'file_history'" in w for w in warnings)
    (root / ".harness" / "settings.local.json").write_text(json.dumps({"file_history": "no"}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(root)


# --- saved chats: resume, fork, new chat --------------------------------------------------------------------

def saved(tmp_path, monkeypatch, **kw):
    return make_session(tmp_path, monkeypatch, save_chats=True, **kw)


def test_the_history_is_stored_beside_the_chat_not_in_the_workspace(tmp_path, monkeypatch):
    s = saved(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    assert s.history.base == s.project.dir / "history" and (s.history.base / f"{s.chat.id}.jsonl").exists()
    assert not (s.ws.root / "history").exists() and list(s.history.base.glob("blobs/*/*"))


def test_a_resumed_chat_can_still_undo(tmp_path, monkeypatch):
    s = saved(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    s.close()
    again = make_session(tmp_path, monkeypatch, save_chats=True)
    again.resume(again.chats()[0])
    assert "put back: a.txt" in run(again, "/undo") and (again.ws.root / "a.txt").read_text(encoding="utf-8") == "one\n"


def test_a_rewind_is_recorded_in_the_chat_log(tmp_path, monkeypatch):
    s = saved(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    edits(s, write("n.py", "x = 1\n"))
    run(s, "/rewind 2")
    found = replay(s.chat.path)
    assert [m for m in found.messages] == s.agent.messages[1:]                        # the log replays to the rewound conversation
    assert any(m.checkpoint for m in found.messages if m.role == "user")              # and the ids came through
    edits(s, write("m.py", "y = 2\n"))
    assert len(replay(s.chat.path).messages) == len(s.agent.messages) - 1


def test_a_new_chat_has_nothing_to_undo_and_the_old_one_keeps_its_history(tmp_path, monkeypatch):
    s = saved(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    old = s.chat.id
    s.reset()
    assert run(s, "/undo") == "no file changes to undo" and (s.history.base / f"{old}.jsonl").exists()


def test_a_fork_starts_with_the_same_history(tmp_path, monkeypatch):
    s = saved(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    original = s.chat.id
    s.fork("branch")
    assert s.chat.id != original and "put back: a.txt" in run(s, "/undo")
    assert (s.history.base / f"{original}.jsonl").exists()


def test_old_chats_take_their_history_with_them(tmp_path, monkeypatch):
    s = saved(tmp_path, monkeypatch, files={"a.txt": "one\n"})
    edits(s, read_file("a.txt"), edit("a.txt", "one", "two"))
    s.close()
    log = s.history.base / f"{s.chat.id}.jsonl"
    old = time.time() - 40 * 86_400
    os.utime(s.chat.path, (old, old))
    again = make_session(tmp_path, monkeypatch, save_chats=True, chat_retention_days=30)
    assert not log.exists() and not s.chat.path.exists() and again.history is not None
