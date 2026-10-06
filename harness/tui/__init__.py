"""Terminal interfaces. `make_ui()` picks the rich one when it can, the plain one otherwise."""
import os
import sys


def make_ui(plain: bool = False, auto_approve: bool = False):
    """Return (ui, approver). Rich needs the `tui` extra and a real terminal."""
    if not plain and not os.environ.get("NO_COLOR") and sys.stdout.isatty():
        try:
            from harness.tui.rich_ui import RichApprover, RichUI
        except ImportError:
            pass
        else:
            ui = RichUI()
            return ui, RichApprover(auto_approve, ui)
    from harness.tui.plain import PlainApprover, PlainUI, enable_ansi
    enable_ansi()
    return PlainUI(), PlainApprover(auto_approve)
