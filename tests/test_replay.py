"""Lesson 15: a real model run, recorded once, replayed on every test run.

The cassette holds what qwen3:4b-instruct actually did when asked to fix the sample project's
bug. Replaying it runs our real tools against a fresh copy of the workspace, so this test
fails if a tool's output, the system prompt or the loop changes in a way the recording didn't
see. Re-record deliberately with scripts/record_cassette.py when that happens.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness.agent import Agent
from harness.cli import SYSTEM_PROMPT
from harness.providers.fake import Normalizer, RecordingProvider, ReplayMismatch, ReplayProvider, text
from harness.tools import default_tools
from harness.tools.fs import workspace_snapshot
from harness.workspace import Workspace

REPO = Path(__file__).resolve().parent.parent
CASSETTE = REPO / "tests" / "cassettes" / "fix_subtotal.jsonl"


def fresh_workspace(tmp_path) -> Path:
    root = tmp_path / "ws"
    shutil.copytree(REPO / "workspace", root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return root


def recorded_task() -> str:
    first = json.loads(CASSETTE.read_text(encoding="utf-8").splitlines()[0])
    return next(m["content"] for m in first["request"] if m["role"] == "user")


def make_agent(root: Path, provider) -> Agent:
    ws = Workspace(root)
    return Agent(provider, default_tools(ws), SYSTEM_PROMPT.format(snapshot=workspace_snapshot(ws)),
                 max_steps=20, approve=lambda call, tool: True)


def test_recorded_fix_replays_and_the_project_tests_pass(tmp_path):
    root = fresh_workspace(tmp_path)
    agent = make_agent(root, ReplayProvider(CASSETTE, root=root))
    agent.run(recorded_task())
    assert agent.stop_reason == "completed"
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                           cwd=root / "project", capture_output=True, text=True)
    assert tests.returncode == 0, tests.stdout


def test_a_changed_tool_result_is_caught(tmp_path):
    root = fresh_workspace(tmp_path)
    cart = root / "project" / "shop" / "cart.py"
    cart.write_text(cart.read_text(encoding="utf-8") + "\n# a change the recording never saw\n", encoding="utf-8")
    agent = make_agent(root, ReplayProvider(CASSETTE, root=root))
    with pytest.raises(ReplayMismatch, match=r"message \d+ \(tool\) differs"):
        agent.run(recorded_task())
    assert [m.role for m in agent.messages] == ["system"]     # rolled back like any failure


def test_record_then_replay_round_trip(tmp_path):
    root = fresh_workspace(tmp_path)
    cassette = tmp_path / "c.jsonl"

    class Answer:
        model = "fake"
        def chat(self, messages, tools):
            return text(f"I see {len(messages)} messages")

    make_agent(root, RecordingProvider(Answer(), cassette, root=root)).run("hi")
    entry = json.loads(cassette.read_text(encoding="utf-8"))
    assert entry["request"][1] == {"role": "user", "content": "hi"}
    assert "read_file" in entry["tools"]
    replayed = make_agent(root, ReplayProvider(cassette, root=root))
    assert replayed.run("hi") == "I see 2 messages"
    with pytest.raises(ReplayMismatch, match="more model calls"):
        replayed.run("again")


def test_normalizer_hides_machine_details(tmp_path):
    n = Normalizer(tmp_path)
    raw = f'File "{tmp_path}\\project\\a.py", took 0.42 s; home {Path.home()}; py {sys.base_prefix}'
    out = n(raw)
    assert out == 'File "[WS]/project/a.py", took [T]s; home [HOME]; py [PYTHON]'


def test_cassettes_contain_no_personal_paths():
    home = str(Path.home())
    for cassette in (REPO / "tests" / "cassettes").glob("*.jsonl"):
        content = cassette.read_text(encoding="utf-8")
        assert home not in content and home.replace("\\", "/") not in content, cassette.name
