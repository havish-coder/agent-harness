"""The attack lab (Lesson 27): a workspace with something worth stealing around it.

`Lab` plays a hostile model: it makes the agent call tools with arguments an attacker chose,
through the real agent loop, tools and approval path, then reports what the model got to see.
The user is modelled as unattended: the lab runs in bypass mode (everything the harness would
let run without asking runs), and every question the harness still asks is answered "no" and
recorded in `lab.asked`. A defense counts only if it holds in that worst case.
"""
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from harness.agent import Agent
from harness.messages import ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.security.permissions import Permissions
from harness.tools import default_tools
from harness.workspace import Workspace

SECRET = "TOP-SECRET-outside-the-workspace"
API_KEY = "sk-lab-0123456789abcdefghijklmnop"   # fake, but shaped like a real key


def make_link(link: Path, target: Path) -> bool:
    """A directory symlink, or on Windows without that privilege, a junction (same effect)."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        if os.name != "nt":
            return False
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    return made.returncode == 0


@dataclass
class Lab:
    base: Path
    root: Path
    outside: Path
    has_link: bool
    asked: list = field(default_factory=list)
    provider: ScriptedProvider | None = None
    ws: Workspace | None = None
    permissions: Permissions | None = None

    def __post_init__(self):
        self.ws = Workspace(self.root)   # one workspace for the whole lab: reads are remembered
        self.permissions = Permissions(self.ws, mode="bypass")

    def approve(self, call, tool, decision=None) -> bool:
        """Unattended user: nobody is there to say yes. Records the question, answers no."""
        self.asked.append((call.name, decision.reason if decision else None))
        return False

    def attack(self, *calls: ToolCall) -> str:
        """Run the calls as one model turn; return everything the model saw afterwards."""
        self.provider = ScriptedProvider([tool_calls(*calls), text("done")])
        Agent(self.provider, default_tools(self.ws), "lab", approve=self.approve, stream=False,
              permissions=self.permissions, fence_untrusted=True, redact_results=True).run("go")
        last_request = self.provider.requests[-1][0]
        return "\n".join(m.content or "" for m in last_request if m.role == "tool")


@pytest.fixture
def lab(tmp_path, monkeypatch) -> Lab:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text(SECRET + "\n", encoding="utf-8")
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (root / ".git" / "hooks").mkdir(parents=True)
    (root / ".harness").mkdir()
    (root / ".harness" / "settings.json").write_text("{}\n", encoding="utf-8")
    (root / ".env").write_text(f"ANTHROPIC_API_KEY={API_KEY}\n", encoding="utf-8")
    has_link = make_link(root / "link", outside)
    monkeypatch.setenv("LAB_API_KEY", API_KEY)
    return Lab(tmp_path, root, outside, has_link)


def call(name: str, id: str = "a1", **arguments) -> ToolCall:
    return ToolCall(id, name, arguments)
