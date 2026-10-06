"""Lesson 23: the key watcher, @mentions and completion."""
import threading
import time

from prompt_toolkit.document import Document

from harness.mentions import expand_mentions
from harness.tools import default_tools
from harness.tui.keys import ESC, KeyWatcher
from harness.tui.prompt import LineReader, make_completer
from harness.workspace import Workspace


class FakeKeyboard:
    def __init__(self):
        self.keys, self.lock = [], threading.Lock()

    def press(self, *keys):
        with self.lock:
            self.keys.extend(keys)

    def waiting(self):
        with self.lock:
            return bool(self.keys)

    def read(self):
        with self.lock:
            return self.keys.pop(0)


def settle(condition, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not condition():
        time.sleep(0.01)
    return condition()


def test_escape_interrupts_and_other_keys_become_typeahead():
    kb, escapes = FakeKeyboard(), []
    watcher = KeyWatcher((kb.waiting, kb.read), on_escape=lambda: escapes.append(1), poll=0.01)
    with watcher.watching():
        kb.press(*"fix it", "\x08", "\x08", *"t", "\r", "\xe0", "H")   # backspaces, Enter, an arrow key
        assert settle(lambda: not kb.waiting())
        kb.press(ESC)
        assert settle(lambda: escapes == [1])
    assert watcher.take_typeahead() == "fix t"
    assert watcher.take_typeahead() == ""


def test_paused_watcher_leaves_keys_alone():
    kb = FakeKeyboard()
    watcher = KeyWatcher((kb.waiting, kb.read), on_escape=lambda: None, poll=0.01)
    with watcher.watching():
        with watcher.paused():
            kb.press("y")
            time.sleep(0.1)
            assert kb.keys == ["y"]          # the approval prompt can read it
        kb.keys.clear()


def test_no_console_means_no_watcher():
    watcher = KeyWatcher(keys=None)
    assert not watcher.available
    with watcher.watching():
        pass


def test_mentions_attach_files_and_count_as_read(tmp_path):
    (tmp_path / "notes.txt").write_text("TODO: a\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    ws = Workspace(tmp_path)
    text, attached = expand_mentions("check @notes.txt and @src, mail me@example.com, @missing.py", ws)
    assert attached == ["notes.txt", "src"]
    assert '<file path="notes.txt">' in text and "TODO: a" in text
    assert '<folder path="src">' in text and "app.py" in text
    tools = {t.name: t for t in default_tools(ws)}
    assert tools["edit_file"].check(path="notes.txt", old_string="TODO", new_string="DONE") is None
    assert expand_mentions("no mentions here", ws) == ("no mentions here", [])


def test_completer_offers_commands_and_files(tmp_path):
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "cart.py").write_text("", encoding="utf-8")
    completer = make_completer(Workspace(tmp_path), ["/reset", "/cost", "/bye"])

    def complete(text):
        return [c.text for c in completer.get_completions(Document(text), None)]

    assert complete("/c") == ["/cost"]
    assert complete("fix @proj") == ["@project/cart.py"]
    assert complete("fix @car") == ["@project/cart.py"]
    assert complete("hello /c") == []          # commands only at the start


def test_line_reader_falls_back_without_a_terminal(tmp_path, monkeypatch):
    reader = LineReader(Workspace(tmp_path))   # pytest's stdin is not a terminal
    assert reader.session is None
    monkeypatch.setattr("builtins.input", lambda prompt: "typed")
    assert reader.read() == "typed"
