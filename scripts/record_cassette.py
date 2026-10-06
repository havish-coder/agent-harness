"""Record a real agent run as a test cassette (Lesson 15).

Run:  python scripts/record_cassette.py fix_subtotal "The cart subtotal in project/shop/cart.py ignores the quantity. Fix it."

Copies workspace/ to a temporary folder, runs the task against the real model with every
tool call approved, saves tests/cassettes/<name>.jsonl, and reports whether the sample
project's tests pass afterwards. Re-record when a deliberate change (a prompt, a tool's
output) makes the replay test fail.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from harness.agent import Agent  # noqa: E402
from harness.cli import SYSTEM_PROMPT  # noqa: E402
from harness.providers.fake import RecordingProvider, committed_copy  # noqa: E402
from harness.providers.ollama import OllamaProvider  # noqa: E402
from harness.tools import default_tools  # noqa: E402
from harness.tools.fs import workspace_snapshot  # noqa: E402
from harness.workspace import Workspace  # noqa: E402


def main(name: str, task: str) -> int:
    root = Path(tempfile.mkdtemp()) / "ws"
    committed_copy(ROOT, "workspace", root)
    ws = Workspace(root)
    cassette = ROOT / "tests" / "cassettes" / f"{name}.jsonl"
    provider = RecordingProvider(OllamaProvider(temperature=0), cassette, root=root)
    agent = Agent(provider, default_tools(ws), SYSTEM_PROMPT.format(snapshot=workspace_snapshot(ws)),
                  max_steps=20, approve=lambda call, tool: True,
                  on_event=lambda k, d: print("  →", d.name, d.arguments) if k == "tool_call" else None)
    answer = agent.run(task)
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                           cwd=root / "project", capture_output=True, text=True)
    print("answer:", answer)
    print("project tests:", tests.stdout.strip().splitlines()[-1])
    print(f"saved {cassette.relative_to(ROOT)} ({len(cassette.read_text(encoding='utf-8').splitlines())} model calls)")
    return 0 if tests.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
