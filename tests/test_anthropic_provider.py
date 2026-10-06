"""Lesson 18: the Anthropic Messages adapter, against a fake server shaped like the real API."""
import json

import httpx
import pytest

from harness.agent import Agent
from harness.messages import Message, ToolCall
from harness.providers.anthropic import AnthropicProvider, to_anthropic
from harness.providers.base import ProviderError, TextDelta
from harness.tools.base import tool

TOOLS = [{"name": "read_file", "description": "Read a file",
          "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}]


def server(handler, **kw):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    return AnthropicProvider(api_key="sk-ant-test", transport=httpx.MockTransport(wrapped), **kw), seen


def sse(*events) -> httpx.Response:
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def start(input_tokens=20, cache_read=0):
    return {"type": "message_start", "message": {"id": "msg_1", "role": "assistant", "content": [],
            "usage": {"input_tokens": input_tokens, "cache_read_input_tokens": cache_read, "output_tokens": 1}}}


def test_conversation_conversion():
    history = [Message.system("You are helpful."), Message.user("read a and b"),
               Message("assistant", "Sure.", tool_calls=[ToolCall("t1", "read_file", {"path": "a"}),
                                                        ToolCall("t2", "read_file", {"path": "b"})]),
               Message.tool_result(ToolCall("t1", "read_file", {}), "A"),
               Message.tool_result(ToolCall("t2", "read_file", {}), "Error: missing"),
               Message("assistant", "Done.")]
    out = to_anthropic(history)
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]   # no system message
    assert out[1]["content"] == [{"type": "text", "text": "Sure."},
                                 {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a"}},
                                 {"type": "tool_use", "id": "t2", "name": "read_file", "input": {"path": "b"}}]
    assert out[2]["content"] == [{"type": "tool_result", "tool_use_id": "t1", "content": "A"},   # both results,
                                 {"type": "tool_result", "tool_use_id": "t2", "content": "Error: missing",  # one message
                                  "is_error": True}]


def test_request_headers_body_and_cache_markers():
    provider, seen = server(lambda r: httpx.Response(200, json={
        "content": [{"type": "text", "text": "Hi"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 3, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 0, "output_tokens": 2}}))
    reply = provider.chat([Message.system("sys"), Message.user("hello")], TOOLS)
    req = seen[0]
    assert req.url == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == "sk-ant-test" and req.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(req.content)
    assert body["max_tokens"] == 8192 and body["model"] == "claude-sonnet-5-5"
    assert body["system"] == [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}]
    assert body["tools"] == [{"name": "read_file", "description": "Read a file",
                              "input_schema": TOOLS[0]["parameters"], "cache_control": {"type": "ephemeral"}}]
    assert body["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert reply.message.content == "Hi" and reply.stop_reason == "end"
    assert reply.usage.input_tokens == 103          # uncached + cached: everything the model read
    assert provider.last_usage["cache_read_input_tokens"] == 100
    assert "sk-ant" not in repr(provider)


def test_caching_can_be_turned_off():
    provider, seen = server(lambda r: httpx.Response(200, json={"content": [], "stop_reason": "end_turn"}), cache=False)
    provider.chat([Message.system("sys"), Message.user("x")], TOOLS)
    assert "cache_control" not in seen[0].content.decode()


def test_stream_text_and_tool_use_with_partial_json():
    provider, _ = server(lambda r: sse(
        start(25),
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "ping"},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Let me "}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "look."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1",
                                                                       "name": "read_file", "input": {}}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"pa'}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": 'th": "notes.txt"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 40}},
        {"type": "message_stop"}))
    items = list(provider.stream([Message.user("read notes")], TOOLS))
    assert items[:2] == [TextDelta("Let me "), TextDelta("look.")]
    reply = items[-1]
    assert reply.message.content == "Let me look."
    assert [(c.id, c.name, c.arguments) for c in reply.message.tool_calls] == [("toolu_1", "read_file", {"path": "notes.txt"})]
    assert reply.stop_reason == "tool_calls" and reply.usage.output_tokens == 40 and reply.usage.input_tokens == 25


def test_errors():
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider(api_key=None)
    provider, _ = server(lambda r: httpx.Response(529, json={"type": "error", "error": {
        "type": "overloaded_error", "message": "Overloaded"}}))
    with pytest.raises(ProviderError, match="overloaded") as e:
        provider.chat([Message.user("x")], [])
    assert e.value.retryable and e.value.status == 529
    provider, _ = server(lambda r: httpx.Response(400, json={"type": "error", "error": {
        "type": "invalid_request_error", "message": "messages: roles must alternate"}}))
    with pytest.raises(ProviderError, match="roles must alternate") as e:
        provider.chat([Message.user("x")], [])
    assert not e.value.retryable
    provider, _ = server(lambda r: sse(start(), {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}))
    with pytest.raises(ProviderError, match="mid-stream") as e:
        list(provider.stream([Message.user("x")], []))
    assert e.value.retryable


def test_full_agent_turn_through_the_adapter():
    replies = iter([
        httpx.Response(200, json={"content": [{"type": "tool_use", "id": "u1", "name": "look", "input": {"x": 1}}],
                                  "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5}}),
        httpx.Response(200, json={"content": [{"type": "text", "text": "Saw 1"}], "stop_reason": "end_turn",
                                  "usage": {"input_tokens": 20, "output_tokens": 3}}),
    ])
    provider, seen = server(lambda r: next(replies))

    @tool(read_only=True)
    def look(x: int) -> str:
        """Look."""
        return f"value {x}"

    agent = Agent(provider, [look], "sys", stream=False)
    assert agent.run("go") == "Saw 1"
    second = json.loads(seen[1].content)["messages"]
    assert second[-1]["content"][0]["type"] == "tool_result" and second[-1]["content"][0]["tool_use_id"] == "u1"
