"""Lesson 23: reading what the user types.

With a real terminal and prompt_toolkit installed: a line editor with persistent history
(↑/↓, Ctrl+R to search), grey suggestions from history (→ to accept), Esc then Enter (or
Alt+Enter) for a new line, and Tab completion for /commands and @file mentions.
Otherwise: plain input().
"""
import sys
from pathlib import Path

from harness.tools.search import walk_files
from harness.workspace import Workspace


def make_completer(ws: Workspace, commands: list[str]):
    from prompt_toolkit.completion import Completer, Completion

    class HarnessCompleter(Completer):
        def get_completions(self, document, complete_event):
            word = document.get_word_before_cursor(WORD=True)
            if word.startswith("/") and document.text_before_cursor.strip() == word:
                for name in commands:
                    if name.startswith(word):
                        yield Completion(name, start_position=-len(word))
            elif word.startswith("@"):
                prefix = word[1:].replace("\\", "/")
                for i, p in enumerate(walk_files(ws.root, ws)):
                    rel = ws.display(p)
                    if rel.startswith(prefix) or ("/" not in prefix and p.name.startswith(prefix)):
                        yield Completion("@" + rel, start_position=-len(word))
                    if i > 2000:
                        break

    return HarnessCompleter()


class LineReader:
    def __init__(self, ws: Workspace, history_file: Path | None = None, commands: list[str] = ()):
        self.session = None
        if not sys.stdin.isatty():
            return
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
            from prompt_toolkit.history import FileHistory, InMemoryHistory
            from prompt_toolkit.key_binding import KeyBindings
        except ImportError:
            return
        bindings = KeyBindings()

        @bindings.add("escape", "enter")          # Esc then Enter, or Alt+Enter: a new line
        def _(event):
            event.current_buffer.insert_text("\n")

        history = InMemoryHistory()
        if history_file is not None:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history = FileHistory(str(history_file))
        self.session = PromptSession(history=history, auto_suggest=AutoSuggestFromHistory(),
                                     completer=make_completer(ws, list(commands)), key_bindings=bindings,
                                     complete_while_typing=False, enable_history_search=True)

    def read(self, prompt: str = "you> ", default: str = "", toolbar=None) -> str:
        if self.session is None:
            return input(f"\n{prompt}")
        from prompt_toolkit.formatted_text import HTML
        print()
        return self.session.prompt(HTML(f"<b>{prompt}</b>"), default=default, bottom_toolbar=toolbar)
