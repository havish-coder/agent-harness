"""Lesson 17: a provider for any server that speaks OpenAI's Chat Completions API.

That's OpenAI itself and most of the ecosystem: Groq, OpenRouter, Together, Mistral, DeepSeek,
Gemini's compatibility endpoint, LM Studio, vLLM, llama.cpp's server, and Ollama's /v1.

Differences from Ollama's native API that this adapter handles:
- tool-call arguments are a JSON *string*, not an object, in both directions;
- tool results are linked to calls by `tool_call_id`;
- streaming uses server-sent events (`data: {...}` lines, then `data: [DONE]`), and a tool
  call's arguments arrive in fragments that must be joined by the call's `index`;
- token counts in a stream only come if asked for (`stream_options.include_usage`).
"""
import json
import uuid
from collections.abc import Iterator

import httpx

from harness.messages import Message, Reply, ToolCall, Usage
from harness.providers.base import ProviderError, StreamItem, TextDelta

FINISH = {"stop": "end", "tool_calls": "tool_calls", "function_call": "tool_calls", "length": "max_tokens"}


class OpenAICompatProvider:
    def __init__(self, model: str, base_url: str = "https://api.openai.com/v1", api_key: str | None = None,
                 temperature: float | None = None, max_tokens: int | None = None, timeout: float = 300,
                 transport: httpx.BaseTransport | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = httpx.Client(base_url=self.base_url, headers=headers, transport=transport,
                                 timeout=httpx.Timeout(timeout, connect=10))

    def __repr__(self):   # never show the key, even in a debugger or a log line
        return f"OpenAICompatProvider(model={self.model!r}, base_url={self.base_url!r})"

    def body(self, messages: list[Message], tools: list[dict], stream: bool) -> dict:
        body: dict = {"model": self.model, "messages": [to_openai(m) for m in messages]}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        return body

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply:
        try:
            r = self.http.post("/chat/completions", json=self.body(messages, tools, stream=False))
        except httpx.ConnectError:
            raise ProviderError(f"cannot connect to {self.base_url}", retryable=True) from None
        except httpx.TimeoutException:
            raise ProviderError("the model took too long to respond", retryable=True) from None
        if r.is_error:
            raise http_error(r)
        return from_openai(r.json())

    def stream(self, messages: list[Message], tools: list[dict]) -> Iterator[StreamItem]:
        text, finish, usage = "", None, {}
        calls: dict[int, dict] = {}            # index → {"id", "name", "arguments" (joined fragments)}
        try:
            with self.http.stream("POST", "/chat/completions", json=self.body(messages, tools, stream=True)) as r:
                if r.is_error:
                    r.read()
                    raise http_error(r)
                for data in sse_data(r.iter_lines()):
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if "error" in chunk:
                        raise ProviderError(f"error mid-stream: {chunk['error']}", retryable=True)
                    usage = chunk.get("usage") or usage
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            text += delta["content"]
                            yield TextDelta(delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), {"id": None, "name": "", "arguments": ""})
                            slot["id"] = tc.get("id") or slot["id"]
                            fn = tc.get("function") or {}
                            slot["name"] += fn.get("name") or ""
                            slot["arguments"] += fn.get("arguments") or ""
                        finish = choice.get("finish_reason") or finish
        except httpx.ConnectError:
            raise ProviderError(f"cannot connect to {self.base_url}", retryable=True) from None
        except httpx.TimeoutException:
            raise ProviderError("the model took too long to respond", retryable=True) from None
        message = {"content": text, "tool_calls": [
            {"id": c["id"], "function": {"name": c["name"], "arguments": c["arguments"]}}
            for _, c in sorted(calls.items())]}
        yield from_openai({"choices": [{"message": message, "finish_reason": finish}], "usage": usage,
                           "model": self.model})


def sse_data(lines) -> Iterator[str]:
    """Server-sent events → the payload of each `data:` field (comments and other fields skipped)."""
    for line in lines:
        if line.startswith("data:"):
            yield line[5:].strip()


def http_error(r: httpx.Response) -> ProviderError:
    try:
        detail = r.json().get("error", r.text)
        detail = detail.get("message", detail) if isinstance(detail, dict) else detail
    except (ValueError, AttributeError):
        detail = r.text
    hint = {401: " (check the API key)", 403: " (the key isn't allowed to do this)",
            404: " (unknown model or wrong base URL?)", 429: " (rate limited)"}.get(r.status_code, "")
    retry_after = r.headers.get("retry-after")
    return ProviderError(f"HTTP {r.status_code}{hint}: {str(detail)[:300]}", status=r.status_code,
                         retryable=r.status_code in (408, 409, 429) or r.status_code >= 500,
                         retry_after=float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else None)


def to_openai(m: Message) -> dict:
    """Harness Message → OpenAI JSON."""
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    out: dict = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["content"] = m.content or None    # some servers reject "" alongside tool calls
        out["tool_calls"] = [{"id": c.id, "type": "function",
                              "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                             for c in m.tool_calls]
    return out


def from_openai(data: dict) -> Reply:
    """OpenAI JSON → harness Reply."""
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    calls = []
    for c in msg.get("tool_calls") or []:
        raw = c["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            args = {"_unparsed": raw}   # the tool then fails with a clear error the model can read
        calls.append(ToolCall(c.get("id") or uuid.uuid4().hex[:12], c["function"]["name"], args))
    stop = FINISH.get(choice.get("finish_reason"), "tool_calls" if calls else "end")
    if calls and stop == "end":
        stop = "tool_calls"
    u = data.get("usage") or {}
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    return Reply(Message("assistant", msg.get("content") or "", tool_calls=calls), stop,
                 Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0), cache_read_tokens=cached or 0),
                 model=data.get("model"))
