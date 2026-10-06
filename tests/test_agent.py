"""Lessons 06-09: the loop, its stop reasons, rollback, and approval of tools that change things."""
import pytest

from harness.agent import DENIED, NO_APPROVER, Agent
from harness.tools.base import tool
from tests.fakes import ScriptedProvider, call, calls, final

log: list[str] = []


@tool(read_only=True)
def look(path: str) -> str:
    """Look at a file."""
    return f"contents of {path}"


@tool
def change(path: str) -> str:
    """Change a file."""
    log.append(path)
    return f"changed {path}"


@pytest.fixture(autouse=True)
def clear_log():
    log.clear()


def make(replies, approve=None, **kw):
    events = []
    agent = Agent(ScriptedProvider(replies), [look, change], "system",
                  on_event=lambda k, d: events.append((k, d)), approve=approve, **kw)
    return agent, events


def tool_results(agent):
    return [m.content for m in agent.messages if m.role == "tool"]


def test_completed():
    agent, _ = make([calls(call("look", path="a")), final("done")])
    assert agent.run("hi") == "done"
    assert agent.stop_reason == "completed"
    assert tool_results(agent) == ["contents of a"]
    assert [m.role for m in agent.messages] == ["system", "user", "assistant", "tool", "assistant"]
    assert (agent.usage.input_tokens, agent.usage.output_tokens) == (20, 10)


def test_max_steps():
    agent, _ = make([calls(call("look", path="a"))] * 3, max_steps=3)
    assert "limit of 3 steps" in agent.run("hi")
    assert agent.stop_reason == "max_steps"


def test_read_only_tools_never_ask():
    asked = []
    agent, _ = make([calls(call("look", path="a")), final("ok")], approve=lambda c, t: asked.append(c) or True)
    agent.run("hi")
    assert asked == []


def test_changing_tools_ask_and_respect_the_answer():
    agent, events = make([calls(call("change", path="a")), final("ok")], approve=lambda c, t: False)
    agent.run("hi")
    assert log == []                                  # never ran
    assert tool_results(agent) == [DENIED]
    assert ("tool_denied", agent.messages[2].tool_calls[0]) in events

    agent, _ = make([calls(call("change", path="b")), final("ok")], approve=lambda c, t: True)
    agent.run("hi")
    assert log == ["b"]


def test_no_approver_means_deny():
    agent, _ = make([calls(call("change", path="a")), final("ok")])
    agent.run("hi")
    assert log == [] and tool_results(agent) == [NO_APPROVER]


def test_invalid_calls_never_reach_approval():
    asked = []
    agent, _ = make([calls(call("change", file="a")), final("ok")], approve=lambda c, t: asked.append(c) or True)
    agent.run("hi")
    assert asked == [] and tool_results(agent)[0].startswith("Error: invalid arguments for change")


def test_rollback_on_error_and_cancel():
    class Exploding:
        model = "x"
        def __init__(self, exc):
            self.exc, self.n = exc, 0
        def chat(self, messages, tools):
            self.n += 1
            if self.n == 2:
                raise self.exc
            return calls(call("look", path="a"))

    for exc, reason in [(RuntimeError("server died"), "error"), (KeyboardInterrupt(), "cancelled")]:
        agent = Agent(Exploding(exc), [look], "system")
        with pytest.raises(type(exc)):
            agent.run("hi")
        assert [m.role for m in agent.messages] == ["system"]
        assert agent.stop_reason == reason
