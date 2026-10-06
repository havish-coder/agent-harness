"""Lesson 36: measuring the conversation against the model's window."""
import json

import pytest

from harness import config
from harness.agent import Agent
from harness.cli import run_turn
from harness.commands import load_commands
from harness.config import Settings
from harness.context.tokens import (
    Breakdown,
    Calibrator,
    ContextBudget,
    breakdown,
    estimate_tokens,
    message_tokens,
    schema_tokens,
)
from harness.context.windows import UNKNOWN_CLOUD_WINDOW, window_for
from harness.messages import Message, ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.session import Session
from harness.tools import default_tools
from harness.tui.plain import PlainApprover, PlainUI
from harness.workspace import Workspace

# --- the estimate --------------------------------------------------------------------------

def test_empty_text_costs_nothing():
    assert estimate_tokens("") == 0


@pytest.mark.parametrize("text, low, high", [
    ("hello", 1, 3),                                   # one short word
    ("The quick brown fox jumps over the lazy dog.", 9, 14),
    ("1234567890", 13, 16),                            # digits are split one by one: ~1.45 tokens each
    ("\n".join(f"test_{i} PASSED [{i}%]" for i in range(40)), 300, 450),
])
def test_estimates_are_in_the_right_range(text, low, high):
    assert low <= estimate_tokens(text) <= high


def test_digits_cost_much_more_than_letters():
    """The reason the common `characters / 4` rule fails on test output and tables."""
    assert estimate_tokens("0123456789" * 10) > 5 * estimate_tokens("abcdefghij" * 10)
    numbers = "\n".join(f"{i:>5}\t{i * 37}" for i in range(100))
    assert estimate_tokens(numbers) > 1.6 * len(numbers) / 4


def test_the_fit_beats_chars_over_four_on_structured_output():
    """Measured on qwen3's tokenizer: 150 lines of pytest output are 2,482 tokens (6000 chars, 2.4 chars per
    token). chars/4 says 1,500 (-40%); this estimate says about 2,340 (-6%)."""
    report = "\n".join(f"tests/test_x.py::test_case_{i} PASSED  [{i}%]" for i in range(150))[:6000]
    assert abs(estimate_tokens(report) - 2482) / 2482 < 0.12
    assert abs(len(report) / 4 - 2482) / 2482 > 0.3


def test_message_tokens_include_overhead_and_tool_calls():
    plain = Message.user("hello there")
    assert message_tokens(plain) == 4 + estimate_tokens("hello there")
    call = ToolCall("c1", "read_file", {"path": "src/app.py"})
    asking = Message("assistant", "", tool_calls=[call])
    assert message_tokens(asking) > 4 + estimate_tokens("read_file") + estimate_tokens(json.dumps({"path": "src/app.py"}))


def test_schemas_cost_tokens_once_per_request(tmp_path):
    schemas = [t.schema() for t in default_tools(Workspace(tmp_path))]
    assert 1000 < schema_tokens(schemas) < 4000 and schema_tokens([]) == 0


def test_breakdown_sorts_every_message_into_a_bucket():
    call = ToolCall("1", "read_file", {"path": "a.py"})
    messages = [Message.system("sys"), Message.user("question"), Message("assistant", "", tool_calls=[call]),
                Message.tool_result(call, "file text " * 50), Message.tool_result(ToolCall("2", "grep", {}), "match"),
                Message("assistant", "answer")]
    parts = breakdown(messages, [{"name": "x", "description": "d", "parameters": {}}])
    assert parts.system > 0 and parts.user > 0 and parts.assistant > 0 and parts.tools > 0
    assert set(parts.results) == {"read_file", "grep"} and parts.results["read_file"] > parts.results["grep"]
    assert parts.total == parts.system + parts.tools + parts.user + parts.assistant + sum(parts.results.values())
    assert Breakdown().total == 0


# --- the budget ----------------------------------------------------------------------------

def conversation(tokens_of_filler: int) -> list[Message]:
    # 'a' costs 0.2 tokens, so 5 per token
    return [Message.system("s"), Message.user("a" * 5 * tokens_of_filler)]


def test_levels_follow_the_share_of_the_limit_used():
    budget = ContextBudget(window=10_000, reserve=2_000)           # the conversation may use 8,000
    assert budget.limit == 8_000
    # the decision uses estimate * 1.1, so these are the estimates that cross each line
    assert budget.check(conversation(3_000)).level == "ok"          # 3.3k of 8k
    assert budget.check(conversation(5_200)).level == "warn"        # 5.7k >= 70%
    assert budget.check(conversation(6_800)).level == "critical"    # 7.5k >= 90%
    assert budget.check(conversation(7_400)).level == "full"        # 8.1k >= the limit


def test_the_status_reports_estimates_and_shares():
    budget = ContextBudget(window=8_192, reserve=1_000)
    status = budget.check(conversation(2_000))
    assert 1_900 < status.estimated < 2_200 and status.window == 8_192 and status.limit == 7_192
    assert status.percent == round(100 * status.estimated / 8_192)


def test_the_reserve_is_never_more_than_the_window():
    assert ContextBudget(window=100, reserve=500).limit == 1


def test_calibration_follows_what_the_server_reports():
    c = Calibrator()
    c.observe(1000, 1200)
    assert c.ratio == pytest.approx(1.2) and c.apply(1000) == 1200
    c.observe(1000, 1200)
    c.observe(1000, 800)
    assert 1.0 < c.ratio < 1.2                                      # smoothed, not jumping
    for _ in range(50):
        c.observe(1000, 5000)
    assert c.ratio == 1.6                                           # clamped
    low = Calibrator()
    for _ in range(50):
        low.observe(1000, 650)
    assert low.ratio == pytest.approx(0.7, abs=0.05)


def test_a_report_that_shows_the_server_cut_the_prompt_is_ignored():
    """Measured on Ollama: a 9,000-word prompt in an 8,192-token window was reported as 45 tokens."""
    c = Calibrator()
    c.observe(10_000, 45)
    c.observe(10_000, 5_000)                                        # under 60% of the estimate: a cut, not a measurement
    assert c.ratio == 1.0 and c.samples == 0


def test_a_calibrated_budget_decides_on_the_calibrated_estimate():
    budget = ContextBudget(window=10_000, reserve=0)
    first = budget.check(conversation(6_500))
    assert first.level == "warn"                                    # 7.2k of 10k
    budget.observe(first, int(first.raw * 1.5))                     # the server reads 50% more than we thought
    again = budget.check(conversation(6_500))
    assert again.estimated > 1.4 * again.raw and again.level in ("critical", "full")


# --- windows -------------------------------------------------------------------------------

@pytest.mark.parametrize("provider, model, configured, explicit, expected", [
    ("ollama", "qwen3:4b-instruct", 8192, False, 8192),
    ("ollama", "qwen3:4b-instruct", 16384, True, 16384),
    ("anthropic", "claude-sonnet-5-5", 8192, False, 200_000),
    ("openai", "gpt-4o-mini", 8192, False, 128_000),
    ("gemini", "gemini-2.5-flash", 8192, False, 1_000_000),
    ("groq", "llama-3.3-70b", 8192, False, 128_000),
    ("openai", "something-new", 8192, False, UNKNOWN_CLOUD_WINDOW),
    ("anthropic", "claude-sonnet-5-5", 50_000, True, 50_000),       # the user's setting always wins
    ("lmstudio", "local", 4096, False, 4096),
])
def test_window_for(provider, model, configured, explicit, expected):
    assert window_for(provider, model, configured, explicit) == expected


# --- in the agent --------------------------------------------------------------------------

@pytest.fixture
def ws(tmp_path):
    (tmp_path / "big.txt").write_text("0123456789 " * 4000, encoding="utf-8")
    return Workspace(tmp_path)


def test_the_agent_reports_the_context_before_each_call(ws):
    events = []
    provider = ScriptedProvider([tool_calls(ToolCall("1", "list_dir", {"path": "."})), text("done")])
    agent = Agent(provider, default_tools(ws), "s", stream=False, context=ContextBudget(8_192, 1_000),
                  on_event=lambda k, d: events.append((k, d)))
    agent.run("hi")
    statuses = [d for k, d in events if k == "context"]
    assert len(statuses) == 2 and statuses[1].estimated > statuses[0].estimated      # the tool result made it bigger
    assert all(s.level == "ok" for s in statuses)


def test_a_conversation_that_wont_fit_stops_before_the_model_is_called(ws):
    provider = ScriptedProvider([text("never reached")])
    agent = Agent(provider, default_tools(ws), "s", stream=False, context=ContextBudget(2_000, 500))
    answer = agent.run("go " * 3_000)
    assert agent.stop_reason == "context_full" and provider.requests == []
    assert "/context shows where they go" in answer and "/reset" in answer


def test_the_agent_calibrates_from_what_the_provider_reports(ws):
    from harness.messages import Reply, Usage
    budget = ContextBudget(8_192, 1_000)
    provider = ScriptedProvider([Reply(Message("assistant", "ok"), "end", Usage(input_tokens=1_800, output_tokens=5))])
    Agent(provider, default_tools(ws), "s", stream=False, context=budget).run("hello")
    assert budget.calibrator.samples == 1 and budget.calibrator.ratio >= 1.0     # the scripted report is far above the estimate


def test_no_budget_means_no_checks(ws):
    provider = ScriptedProvider([text("fine")])
    assert Agent(provider, default_tools(ws), "s", stream=False).run("go " * 20_000) == "fine"


# --- the session ---------------------------------------------------------------------------

class Quiet(PlainUI):
    def __call__(self, kind, data):
        pass

    def warn(self, text_):
        pass


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    s = Session(Settings(), Workspace(tmp_path), Quiet(), PlainApprover())
    s.agent.stream = False
    return s


def test_the_session_plans_for_the_window_with_room_for_the_reply(session):
    assert session.context.window == 8_192 and session.context.reserve == 2_048     # a quarter, not the whole 4,096
    assert session.status()["context_window"] == 8_192


def test_a_cloud_model_gets_its_own_window(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    s = Session(Settings(provider="anthropic", model="claude-sonnet-5-5"), Workspace(tmp_path), Quiet(), PlainApprover())
    assert s.context.window == 200_000 and s.status()["context_window"] == 200_000


def test_the_status_estimate_grows_with_the_conversation(session):
    before = session.estimate_context()
    session.agent.messages.append(Message.user("x" * 8_000))
    assert session.estimate_context() > before + 1_000


def test_the_context_command_shows_where_the_tokens_go(session):
    session.agent.provider = ScriptedProvider([tool_calls(ToolCall("1", "read_file", {"path": "big.txt"})), text("done")])
    (session.ws.root / "big.txt").write_text("0123456789 " * 400, encoding="utf-8")
    session.agent.run("read big.txt")
    out = load_commands(session.ws.root).parse("/context")[0].run(session, "")
    for label in ("system prompt", "tool definitions", "your messages", "assistant", "tool results"):
        assert label in out
    assert "read_file" in out and "of 8,192 tokens" in out and "are kept free for the reply" in out
    assert "plenty of room" in out or "getting full" in out


def test_the_context_command_warns_when_it_does_not_fit(session):
    session.agent.messages.append(Message.user("9" * 20_000))
    assert "does not fit" in load_commands(session.ws.root).parse("/context")[0].run(session, "")


def test_the_usage_line_after_a_turn_uses_the_estimate(session, capsys):
    from harness.tui.keys import KeyWatcher
    session.agent.provider = ScriptedProvider([text("hello")])
    shown = []
    session.ui.usage_line = shown.append
    session.ui.answer = lambda a: None
    run_turn(session, KeyWatcher(), "hi")
    assert shown and "context ~" in shown[0]
