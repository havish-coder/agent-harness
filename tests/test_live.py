"""Tests against a real model. Skipped by default; run with:  pytest -m live

They need Ollama running with qwen3:4b-instruct pulled. Model output varies, so these check
behaviour (did it use a tool, does the answer contain the fact), never exact text.
"""
import httpx
import pytest

from harness.agent import Agent
from harness.cli import SYSTEM_PROMPT
from harness.providers.ollama import OllamaProvider
from harness.tools import default_tools
from harness.tools.fs import workspace_snapshot
from harness.workspace import Workspace

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def ollama():
    try:
        httpx.get("http://localhost:11434/api/tags", timeout=2).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("Ollama is not running")
    return OllamaProvider()


def test_reads_a_file_to_answer(ollama, tmp_path):
    (tmp_path / "notes.txt").write_text("TODO: a\nDONE: b\nTODO: c\n", encoding="utf-8")
    ws = Workspace(tmp_path)
    used = []
    agent = Agent(ollama, default_tools(ws), SYSTEM_PROMPT.format(snapshot=workspace_snapshot(ws)),
                  on_event=lambda k, d: used.append(d.name) if k == "tool_call" else None)
    answer = agent.run("How many TODOs are in notes.txt?")
    assert used, "the model answered without looking"
    assert "2" in answer


def test_anthropic_reads_a_file(tmp_path):
    """Runs only if ANTHROPIC_API_KEY is set; costs a fraction of a cent."""
    import os

    from harness.providers.factory import make_provider
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set")
    (tmp_path / "notes.txt").write_text("TODO: a\nDONE: b\nTODO: c\n", encoding="utf-8")
    ws = Workspace(tmp_path)
    provider = make_provider("anthropic", "claude-haiku-4-5-20251001")
    used = []
    agent = Agent(provider, default_tools(ws), SYSTEM_PROMPT.format(snapshot=workspace_snapshot(ws)),
                  on_event=lambda k, d: used.append(d.name) if k == "tool_call" else None)
    assert "2" in agent.run("How many TODOs are in notes.txt?") and used
