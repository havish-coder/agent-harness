"""Lessons 05 and 16: the Ollama adapter's wire format, checked against a fake server."""
import json

import httpx
import pytest

from harness.agent import Agent
from harness.messages import Message, ToolCall
from harness.providers.base import ProviderError, StreamingProvider, TextDelta, ThinkingDelta
from harness.providers.ollama import OllamaProvider
from harness.tools.base import tool

TOOLS = [{"name": "read_file", "description": "Read", "parameters": {"type": "object", "properties": {}}}]


def server(handler):
    """An OllamaProvider talking to `handler(request) -> httpx.Response` instead of a real server."""
    seen = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return handler(request)

    return OllamaProvider(transport=httpx.MockTransport(wrapped)), seen


def ndjson(*chunks) -> httpx.Response:
    return httpx.Response(200, content="\n".join(json.dumps(c) for c in chunks).encode())


def test_request_body_and_reply_parsing():
    provider, seen = server(lambda r: httpx.Response(200, json={
        "message": {"role": "assistant", "content": "",
                    "tool_calls": [{"id": "t1", "function": {"name": "read_file", "arguments": {"path": "a"}}}]},
        "done": True, "done_reason": "stop", "prompt_eval_count": 42, "eval_count": 7}))
    history = [Message.system("sys"), Message.user("hi"),
               Message("assistant", tool_calls=[ToolCall("t0", "read_file", {"path": "x"})]),
               Message.tool_result(ToolCall("t0", "read_file", {}), "content of x")]
    reply = provider.chat(history, TOOLS)
    body = seen[0]
    assert body["stream"] is False and body["model"] == "qwen3:4b-instruct"
    assert body["tools"] == [{"type": "function", "function": TOOLS[0]}]
    assert body["messages"][2]["tool_calls"] == [{"id": "t0", "function": {"name": "read_file", "arguments": {"path": "x"}}}]
    assert body["messages"][3] == {"role": "tool", "content": "content of x", "tool_name": "read_file"}
    assert reply.stop_reason == "tool_calls" and reply.message.tool_calls[0].arguments == {"path": "a"}
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (42, 7)


def test_streaming_text_then_the_reply():
    provider, seen = server(lambda r: ndjson(
        {"message": {"content": "Hel"}, "done": False},
        {"message": {"content": "lo!"}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "stop", "prompt_eval_count": 9, "eval_count": 2}))
    items = list(provider.stream([Message.user("hi")], []))
    assert seen[0]["stream"] is True
    assert items[:2] == [TextDelta("Hel"), TextDelta("lo!")]
    reply = items[-1]
    assert reply.message.content == "Hello!" and reply.stop_reason == "end" and reply.usage.input_tokens == 9


def test_streamed_tool_calls_and_thinking():
    provider, _ = server(lambda r: ndjson(
        {"message": {"thinking": "Let me check. "}, "done": False},
        {"message": {"content": "", "tool_calls": [{"id": "x", "function": {"name": "read_file",
                                                                             "arguments": '{"path": "n.txt"}'}}]},
         "done": True, "done_reason": "stop", "prompt_eval_count": 5, "eval_count": 3}))
    provider.think = True
    items = list(provider.stream([Message.user("read")], TOOLS))
    assert items[0] == ThinkingDelta("Let me check. ")
    assert items[-1].message.tool_calls[0].arguments == {"path": "n.txt"}   # JSON-string arguments parsed


def test_cut_off_and_leaked_thinking():
    provider, _ = server(lambda r: httpx.Response(200, json={
        "message": {"content": "reasoning here</think>\n\nThe answer"}, "done": True, "done_reason": "length"}))
    reply = provider.chat([Message.user("q")], [])
    assert reply.message.content == "The answer" and reply.stop_reason == "max_tokens"


def test_errors_say_whether_to_retry():
    provider, _ = server(lambda r: httpx.Response(500, text='{"error":"CUDA error"}'))
    with pytest.raises(ProviderError) as e:
        provider.chat([Message.user("q")], [])
    assert e.value.status == 500 and e.value.retryable

    provider, _ = server(lambda r: httpx.Response(404, text='{"error":"model not found"}'))
    with pytest.raises(ProviderError) as e:
        list(provider.stream([Message.user("q")], []))
    assert e.value.status == 404 and not e.value.retryable

    provider, _ = server(lambda r: ndjson({"message": {"content": "pa"}, "done": False}, {"error": "runner died"}))
    with pytest.raises(ProviderError, match="mid-stream"):
        list(provider.stream([Message.user("q")], []))


def test_unreachable_server():
    def refuse(request):
        raise httpx.ConnectError("refused")
    provider, _ = server(refuse)
    with pytest.raises(ProviderError, match="cannot connect"):
        provider.chat([Message.user("q")], [])


def test_agent_streams_deltas_before_tool_calls_and_answer():
    replies = iter([
        ndjson({"message": {"content": "Checking."}, "done": False},
               {"message": {"tool_calls": [{"id": "1", "function": {"name": "look", "arguments": {}}}]},
                "done": True, "done_reason": "stop"}),
        ndjson({"message": {"content": "Done"}, "done": False}, {"message": {}, "done": True, "done_reason": "stop"}),
    ])
    provider, _ = server(lambda r: next(replies))
    assert isinstance(provider, StreamingProvider)

    @tool(read_only=True)
    def look() -> str:
        """Look."""
        return "seen"

    events = []
    agent = Agent(provider, [look], "s", on_event=lambda k, d: events.append(k))
    assert agent.run("go") == "Done"
    assert events == ["model_call", "text_delta", "model_reply", "tool_call", "permission", "tool_result",
                      "model_call", "text_delta", "model_reply"]


def test_stream_can_be_turned_off():
    provider, seen = server(lambda r: httpx.Response(200, json={"message": {"content": "ok"}, "done": True}))
    agent = Agent(provider, [], "s", stream=False)
    assert agent.run("go") == "ok" and seen[0]["stream"] is False


def test_output_limit_reaches_every_provider(monkeypatch):
    """A model stuck repeating itself must be stopped: Ollama alone would generate forever."""
    from harness.providers.factory import make_provider
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    assert make_provider("ollama", max_output_tokens=512).options["num_predict"] == 512
    assert make_provider("anthropic", max_output_tokens=512).max_tokens == 512
    assert make_provider("openai", "gpt-x", max_output_tokens=512).max_tokens == 512
    assert "num_predict" not in OllamaProvider().options   # no limit unless asked
