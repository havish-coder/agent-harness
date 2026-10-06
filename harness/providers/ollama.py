"""Lessons 05 and 16: adapter between the harness's types and Ollama's /api/chat dialect.

Streaming: Ollama sends one JSON object per line (NDJSON). Text arrives a token at a time;
tool calls arrive whole, in the final chunk, together with the token counts.
"""
import json
import re
import uuid
from collections.abc import Iterator

import httpx

from harness.messages import Message, Reply, ToolCall, Usage
from harness.providers.base import ProviderError, StreamItem, TextDelta, ThinkingDelta

# Thinking-only models can leak their reasoning into `content`, ending with </think> (Lesson 01).
LEAKED_THINKING = re.compile(r"^.*?</think>\s*", re.DOTALL)


class OllamaProvider:
    def __init__(self, model="qwen3:4b-instruct", url="http://localhost:11434",
                 num_ctx=8192, temperature=None, timeout=300, think: bool | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.model = model
        self.url = url
        self.options = {"num_ctx": num_ctx}
        if temperature is not None:
            self.options["temperature"] = temperature
        self.think = think   # True: thinking models put their reasoning in a separate field
        # transport: tests pass an httpx.MockTransport to fake the server (Lesson 16)
        self.http = httpx.Client(base_url=url, timeout=httpx.Timeout(timeout, connect=10), transport=transport)

    def body(self, messages: list[Message], tools: list[dict], stream: bool) -> dict:
        body = {
            "model": self.model,
            "messages": [to_ollama(m) for m in messages],
            "stream": stream,
            "options": self.options,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        if self.think is not None:
            body["think"] = self.think
        return body

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply:
        try:
            r = self.http.post("/api/chat", json=self.body(messages, tools, stream=False))
        except httpx.ConnectError:
            raise ProviderError(f"cannot connect to Ollama at {self.url}. Is it running?", retryable=True) from None
        except httpx.TimeoutException:
            raise ProviderError("the model took too long to respond", retryable=True) from None
        if r.is_error:
            raise http_error(r.status_code, r.text)
        return from_ollama(r.json())

    def stream(self, messages: list[Message], tools: list[dict]) -> Iterator[StreamItem]:
        merged: dict = {"message": {"content": "", "thinking": "", "tool_calls": []}}
        try:
            # Leaving this `with` early (Ctrl+C, an error) closes the connection, and Ollama
            # stops generating.
            with self.http.stream("POST", "/api/chat", json=self.body(messages, tools, stream=True)) as r:
                if r.is_error:
                    r.read()
                    raise http_error(r.status_code, r.text)
                for line in r.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise ProviderError(f"Ollama error mid-stream: {chunk['error']}", retryable=True)
                    msg = chunk.get("message", {})
                    if msg.get("thinking"):
                        merged["message"]["thinking"] += msg["thinking"]
                        yield ThinkingDelta(msg["thinking"])
                    if msg.get("content"):
                        merged["message"]["content"] += msg["content"]
                        yield TextDelta(msg["content"])
                    merged["message"]["tool_calls"] += msg.get("tool_calls", [])
                    if chunk.get("done"):
                        merged.update({k: v for k, v in chunk.items() if k != "message"})
        except httpx.ConnectError:
            raise ProviderError(f"cannot connect to Ollama at {self.url}. Is it running?", retryable=True) from None
        except httpx.TimeoutException:
            raise ProviderError("the model took too long to respond", retryable=True) from None
        yield from_ollama(merged)


def http_error(status: int, text: str) -> ProviderError:
    # 5xx: the server had a problem (e.g. the GPU runner crashed); trying again may work.
    return ProviderError(f"Ollama returned HTTP {status}: {text}", status=status, retryable=status >= 500)


def to_ollama(m: Message) -> dict:
    """Harness Message → Ollama JSON."""
    out = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {"id": c.id, "function": {"name": c.name, "arguments": c.arguments}} for c in m.tool_calls
        ]
    if m.role == "tool":
        out["tool_name"] = m.tool_name
    return out


def from_ollama(data: dict) -> Reply:
    """Ollama JSON → harness Reply."""
    msg = data["message"]
    content = msg.get("content", "")
    if "</think>" in content:
        content = LEAKED_THINKING.sub("", content, count=1)

    calls = []
    for c in msg.get("tool_calls", []):
        args = c["function"].get("arguments") or {}
        if isinstance(args, str):  # some models emit arguments as a JSON string
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_unparsed": args}  # let the tool fail with a clear error instead of crashing here
        calls.append(ToolCall(id=c.get("id") or uuid.uuid4().hex[:12], name=c["function"]["name"], arguments=args))

    if data.get("done_reason") == "length":
        stop = "max_tokens"
    else:
        stop = "tool_calls" if calls else "end"
    # prompt_eval_cached_count: prompt tokens Ollama reused from its cache of the previous request
    usage = Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0),
                  cache_read_tokens=data.get("prompt_eval_cached_count", 0))
    return Reply(Message("assistant", content, tool_calls=calls), stop, usage, model=data.get("model"))
