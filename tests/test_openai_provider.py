"""Lesson 17: the OpenAI-compatible adapter, against a fake server."""
import json

import httpx
import pytest

from harness.messages import Message, ToolCall
from harness.providers.base import ProviderError, TextDelta
from harness.providers.openai_compat import OpenAICompatProvider

TOOLS = [{"name": "read_file", "description": "Read", "parameters": {"type": "object", "properties": {}}}]


def server(handler, **kw):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    return OpenAICompatProvider("m", base_url="https://api.example/v1", transport=httpx.MockTransport(wrapped), **kw), seen


def sse(*chunks) -> httpx.Response:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def test_request_shape_and_key():
    provider, seen = server(lambda r: httpx.Response(200, json={
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3}}), api_key="sk-secret", temperature=0)
    history = [Message.system("sys"), Message.user("q"),
               Message("assistant", tool_calls=[ToolCall("c1", "read_file", {"path": "a.txt"})]),
               Message.tool_result(ToolCall("c1", "read_file", {}), "file text")]
    reply = provider.chat(history, TOOLS)
    req = seen[0]
    assert req.url == "https://api.example/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-secret"
    body = json.loads(req.content)
    assert body["temperature"] == 0 and "stream" not in body
    assert body["messages"][2] == {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}]}
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "file text"}
    assert reply.message.content == "hi" and reply.stop_reason == "end"
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (12, 3)
    assert "sk-secret" not in repr(provider)


def test_tool_call_reply_with_bad_json_arguments():
    provider, _ = server(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "a", "function": {"name": "read_file", "arguments": '{"path": "x"}'}},
        {"id": "b", "function": {"name": "read_file", "arguments": '{"path": '}}]}, "finish_reason": "tool_calls"}]}))
    reply = provider.chat([Message.user("q")], TOOLS)
    assert reply.stop_reason == "tool_calls"
    assert [c.arguments for c in reply.message.tool_calls] == [{"path": "x"}, {"_unparsed": '{"path": '}]


def test_stream_text_and_usage_chunk():
    provider, seen = server(lambda r: sse(
        {"choices": [{"delta": {"role": "assistant", "content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}))
    items = list(provider.stream([Message.user("q")], []))
    body = json.loads(seen[0].content)
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
    assert items[:2] == [TextDelta("Hel"), TextDelta("lo")]
    assert items[-1].message.content == "Hello" and items[-1].usage.output_tokens == 2


def test_stream_assembles_tool_call_fragments_by_index():
    provider, _ = server(lambda r: sse(
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c0", "function": {"name": "read_", "arguments": ""}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "file", "arguments": '{"pa'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "c1", "function": {"name": "grep", "arguments": '{"pattern": "x"}'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'th": "a"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}))
    reply = list(provider.stream([Message.user("q")], TOOLS))[-1]
    assert [(c.id, c.name, c.arguments) for c in reply.message.tool_calls] == [
        ("c0", "read_file", {"path": "a"}), ("c1", "grep", {"pattern": "x"})]
    assert reply.stop_reason == "tool_calls"


def test_errors():
    provider, _ = server(lambda r: httpx.Response(401, json={"error": {"message": "Invalid API key"}}))
    with pytest.raises(ProviderError, match=r"401 \(check the API key\): Invalid API key") as e:
        provider.chat([Message.user("q")], [])
    assert not e.value.retryable

    provider, _ = server(lambda r: httpx.Response(429, json={"error": {"message": "slow down"}}, headers={"retry-after": "7"}))
    with pytest.raises(ProviderError) as e:
        list(provider.stream([Message.user("q")], []))
    assert e.value.retryable and e.value.retry_after == 7.0 and e.value.status == 429

    provider, _ = server(lambda r: sse({"choices": [{"delta": {"content": "a"}}]}, {"error": {"message": "overloaded"}}))
    with pytest.raises(ProviderError, match="mid-stream"):
        list(provider.stream([Message.user("q")], []))


def test_cut_off_reply():
    provider, _ = server(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "partial"},
                                                                         "finish_reason": "length"}]}))
    assert provider.chat([Message.user("q")], []).stop_reason == "max_tokens"
