"""The built-in tools. `default_tools(ws)` is the set every interface gives the agent."""
from harness.tools.base import Tool
from harness.workspace import Workspace


def default_tools(ws: Workspace, shell: str | None = None, env_keep=(), web: bool = False,
                  web_allow_local=(), sandbox=None, sandbox_network: bool = True,
                  sandbox_required: bool = False) -> list[Tool]:
    from harness.tools.edit import make_edit_tools
    from harness.tools.fs import make_fs_tools
    from harness.tools.search import make_search_tools
    from harness.tools.shell import detect_shell, make_shell_tools
    tools = make_fs_tools(ws) + make_search_tools(ws) + make_edit_tools(ws) + make_shell_tools(ws, detect_shell(shell), env_keep, sandbox, sandbox_network, sandbox_required)
    if web:
        from harness.tools.web import make_web_tools
        tools += make_web_tools(web_allow_local)
    return tools
