"""Lesson 23: watch the keyboard while the agent works.

- Esc stops the running task (like Ctrl+C, which keeps working too).
- Anything else you type is kept and offered as the start of your next message ("type-ahead"),
  instead of being lost or garbling the screen.

The watcher runs on a background thread and interrupts the main thread with
`_thread.interrupt_main()`, which raises KeyboardInterrupt there: the agent's existing
cancel-and-roll-back path does the rest. It must pause while something else reads the keyboard
(an approval prompt), or it would steal the user's answer.
"""
import _thread
import os
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager

ESC = "\x1b"


def console_keys() -> tuple[Callable[[], bool], Callable[[], str]] | None:
    """(key_waiting, read_key) for this platform's console, or None if there's no console."""
    if not sys.stdin.isatty():
        return None
    if os.name == "nt":
        import msvcrt
        return msvcrt.kbhit, msvcrt.getwch
    import select
    return (lambda: bool(select.select([sys.stdin], [], [], 0)[0])), (lambda: sys.stdin.read(1))


class KeyWatcher:
    def __init__(self, keys: tuple[Callable[[], bool], Callable[[], str]] | None = None,
                 on_escape: Callable[[], None] = _thread.interrupt_main, poll: float = 0.05):
        self.keys = keys if keys is not None else console_keys()
        self.on_escape = on_escape
        self.poll = poll
        self.typeahead = ""
        self._running = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None
        self._raw = None                       # saved terminal settings (POSIX)

    @property
    def available(self) -> bool:
        return self.keys is not None

    def _loop(self):
        waiting, read = self.keys
        while self._running.is_set():
            if not self._paused.is_set() and waiting():
                key = read()
                if key == ESC:
                    self.on_escape()
                elif key in ("\x00", "\xe0"):        # Windows: first half of an arrow/function key
                    read()
                elif key == "\x08":                   # backspace edits the type-ahead
                    self.typeahead = self.typeahead[:-1]
                elif key in ("\r", "\n"):
                    self.typeahead += " "
                elif key.isprintable():
                    self.typeahead += key
            else:
                time.sleep(self.poll)

    @contextmanager
    def watching(self):
        """Watch the keyboard for the duration of a `with` block (one agent turn)."""
        if not self.available:
            yield self
            return
        self._enter_cbreak()
        self._running.set()
        self._paused.clear()
        self._thread = threading.Thread(target=self._loop, name="key-watcher", daemon=True)
        self._thread.start()
        try:
            yield self
        finally:
            self._running.clear()
            self._thread.join(timeout=1)
            self._leave_cbreak()

    @contextmanager
    def paused(self):
        """Let someone else read the keyboard (an approval prompt) for a moment."""
        self._paused.set()
        time.sleep(self.poll * 2)              # let the loop notice before the prompt starts reading
        self._leave_cbreak()
        try:
            yield
        finally:
            self._enter_cbreak()
            self._paused.clear()

    def take_typeahead(self) -> str:
        text, self.typeahead = self.typeahead, ""
        return text.strip()

    # POSIX terminals deliver keys only after Enter unless switched to cbreak mode.
    def _enter_cbreak(self):
        if os.name == "nt" or not self.available or not sys.stdin.isatty():
            return
        import termios
        import tty
        self._raw = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

    def _leave_cbreak(self):
        if self._raw is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._raw)
            self._raw = None
