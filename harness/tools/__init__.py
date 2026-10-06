"""The built-in tools. `default_tools(ws)` is the set every interface gives the agent."""
from harness.tools.base import Tool
from harness.workspace import Workspace


def default_tools(ws: Workspace) -> list[Tool]:
    from harness.tools.edit import make_edit_tools
    from harness.tools.fs import make_fs_tools
    from harness.tools.search import make_search_tools
    return make_fs_tools(ws) + make_search_tools(ws) + make_edit_tools(ws)
