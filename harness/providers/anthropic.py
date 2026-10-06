"""Lesson 18: a provider for Anthropic's Messages API (Claude models).

The Messages API differs from the chat formats we've seen:
- the system prompt is a separate top-level field, not a message;
- message content is a list of typed blocks (text, tool_use, tool_result, thinking);
- tool results are *user* messages holding tool_result blocks, and all results for one
  assistant turn go in a single user message;
- streaming uses named SSE events (message_start, content_block_delta, ...), and tool inputs
  stream as partial JSON;
- prompt caching is explicit: cache_control markers say where a reusable prefix ends.
"""
import json
from collections.abc import Iterator

import httpx

from harness.messages import Message, Reply, ToolCall, Usage
from harness.providers.base import ProviderError, StreamItem, TextDelta, ThinkingDelta

API_VERSION = "2023-06-01"
STOP = {"end_turn": "end", "stop_sequence": "end", "tool_use": "tool_calls", "max_tokens": "max_tokens",
        "pause_turn": "end", "refusal": "end"}
CACHE = {"type": "ephemeral"}


class AnthropicProvider:
    def __init__(self, model: str = "claude-sonnet-5-5", api_key: str | None = None,
                 base_url: str = "https://api.anthropic.com", max_tokens: int = 8192,
                 temperature: float | None = None, cache: bool = True, timeout: float = 300,
                 transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise ProviderError("the Anthropic provider needs an API key: set ANTHROPIC_API_KEY")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens          # required by this API
        self.temperature = temperature
        self.cache = cache                    # add prompt-caching markers (Lesson 18, 21)
        self.last_usage: dict = {}            # raw usage of the last call, incl. cache counts
        self.http = httpx.Client(base_url=self.base_url, transport=transport,
                                 headers={"x-api-key": api_key, "anthropic-version": API_VERSION},
                                 timeout=httpx.Timeout(timeout, connect=10))

    def __repr__(self):
        return f"AnthropicProvider(model={self.model!r})"

    def body(self, messages: list[Message], tools: list[dict], stream: bool) -> dict:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        body: dict = {"model": self.model, "max_tokens": self.max_tokens, "messages": to_anthropic(messages)}
        if system:
            body["system"] = [{"type": "text", "text": system}]
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                             for t in tools]
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if stream:
            body["stream"] = True
        if self.cache:
            add_cache_markers(body)
        return body

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply:
        try:
            r = self.http.post("/v1/messages", json=self.body(messages, tools, stream=False))
        except httpx.ConnectError:
            raise ProviderError(f"cannot connect to {self.base_url}", retryable=True) from None
        except httpx.TimeoutException:
            raise ProviderError("the model took too long to respond", retryable=True) from None
        if r.is_error:
            raise http_error(r)
        data = r.json()
        self.last_usage = data.get("usage", {})
        return from_anthropic(data)

    def stream(self, messages: list[Message], tools: list[dict]) -> Iterator[StreamItem]:
        message: dict = {"content": [], "stop_reason": None, "usage": {}}
        json_parts: dict[int, str] = {}       # block index → partial JSON of a tool_use input
        try:
            with self.http.stream("POST", "/v1/messages", json=self.body(messages, tools, stream=True)) as r:
                if r.is_error:
                    r.read()
                    raise http_error(r)
                for event, data in sse_events(r.iter_lines()):
                    if event == "message_start":
                        message["usage"].update(data["message"].get("usage", {}))
                    elif event == "content_block_start":
                        block = dict(data["content_block"])
                        message["content"].append(block)
                        if block["type"] == "tool_use":
                            json_parts[data["index"]] = ""
                    elif event == "content_block_delta":
                        block, delta = message["content"][data["index"]], data["delta"]
                        if delta["type"] == "text_delta":
                            block["text"] = block.get("text", "") + delta["text"]
                            yield TextDelta(delta["text"])
                        elif delta["type"] == "thinking_delta":
                            block["thinking"] = block.get("thinking", "") + delta["thinking"]
                            yield ThinkingDelta(delta["thinking"])
                        elif delta["type"] == "input_json_delta":
                            json_parts[data["index"]] += delta["partial_json"]
                    elif event == "content_block_stop" and data["index"] in json_parts:
                        raw = json_parts.pop(data["index"]) or "{}"
                        try:
                            message["content"][data["index"]]["input"] = json.loads(raw)
                        except json.JSONDecodeError:
                            message["content"][data["index"]]["input"] = {"_unparsed": raw}
                    elif event == "message_delta":
                        message["stop_reason"] = data["delta"].get("stop_reason") or message["stop_reason"]
                        message["usage"].update(data.get("usage", {}))
                    elif event == "error":
                        err = data.get("error", {})
                        raise ProviderError(f"Anthropic error mid-stream: {err.get('message', data)}",
                                            retryable=err.get("type") in ("overloaded_error", "api_error"))
        except httpx.ConnectError:
            raise ProviderError(f"cannot connect to {self.base_url}", retryable=True) from None
        except httpx.TimeoutException:
            raise ProviderError("the model took too long to respond", retryable=True) from None
        self.last_usage = message["usage"]
        yield from_anthropic({**message, "model": self.model})


def sse_events(lines) -> Iterator[tuple[str, dict]]:
    """Named server-sent events → (event name, JSON data)."""
    event, data = None, []
    for line in lines:
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line and data:              # a blank line ends one event
            payload = json.loads("\n".join(data))
            yield event or payload.get("type", ""), payload
            event, data = None, []
    if data:
        payload = json.loads("\n".join(data))
        yield event or payload.get("type", ""), payload


def http_error(r: httpx.Response) -> ProviderError:
    try:
        err = r.json().get("error", {})
        detail, kind = err.get("message", r.text), err.get("type", "")
    except (ValueError, AttributeError):
        detail, kind = r.text, ""
    hint = {401: " (check ANTHROPIC_API_KEY)", 404: " (unknown model?)", 429: " (rate limited)",
            529: " (the API is overloaded)"}.get(r.status_code, "")
    retry_after = r.headers.get("retry-after")
    return ProviderError(f"Anthropic HTTP {r.status_code}{hint}: {detail[:300]}", status=r.status_code,
                         retryable=r.status_code in (408, 409, 429) or r.status_code >= 500 or kind == "overloaded_error",
                         retry_after=float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else None)


def to_anthropic(messages: list[Message]) -> list[dict]:
    """Harness messages → Anthropic messages. Consecutive tool results merge into one user message."""
    out: list[dict] = []
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            if m.content.startswith("Error:"):
                block["is_error"] = True
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and all(b.get("type") == "tool_result" for b in out[-1]["content"]):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif m.role == "assistant":
            blocks: list[dict] = [{"type": "text", "text": m.content}] if m.content else []
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in m.tool_calls]
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        else:
            out.append({"role": "user", "content": [{"type": "text", "text": m.content}]})
    return out


def add_cache_markers(body: dict) -> None:
    """Mark where the reusable prefix ends: the system prompt, the tools, and the newest message.

    The API caches everything up to each marker. On the next call the system prompt, the tools
    and the whole previous conversation are a prefix of the new request, so they're read from
    the cache (cheaper and faster) instead of being processed again.
    """
    if body.get("system"):
        body["system"][-1]["cache_control"] = CACHE
    if body.get("tools"):
        body["tools"][-1]["cache_control"] = CACHE
    if body["messages"]:
        content = body["messages"][-1]["content"]
        if isinstance(content, list) and content:
            content[-1] = {**content[-1], "cache_control": CACHE}


def from_anthropic(data: dict) -> Reply:
    """Anthropic message → harness Reply."""
    text, calls = [], []
    for block in data.get("content", []):
        if block.get("type") == "text":
            text.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            calls.append(ToolCall(block["id"], block["name"], block.get("input") or {}))
    u = data.get("usage", {})
    cache_read, cache_write = u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0
    # input_tokens excludes cached tokens on this API; report everything the model read
    read = (u.get("input_tokens") or 0) + cache_read + cache_write
    stop = STOP.get(data.get("stop_reason"), "tool_calls" if calls else "end")
    return Reply(Message("assistant", "".join(text), tool_calls=calls), stop,
                 Usage(read, u.get("output_tokens") or 0, cache_read, cache_write), model=data.get("model"))
