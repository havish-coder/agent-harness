"""The built-in tools. `default_tools(ws)` is the set every interface gives the agent."""
from harness.tools.base import Tool
from harness.workspace import Workspace


def default_tools(ws: Workspace, shell: str | None = None, env_keep=()) -> list[Tool]:
    from harness.tools.edit import make_edit_tools
    from harness.tools.fs import make_fs_tools
    from harness.tools.search import make_search_tools
    from harness.tools.shell import detect_shell, make_shell_tools
    return make_fs_tools(ws) + make_search_tools(ws) + make_edit_tools(ws) + make_shell_tools(ws, detect_shell(shell), env_keep)
