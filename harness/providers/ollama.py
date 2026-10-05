"""Lesson 05: adapter between the harness's types and Ollama's /api/chat dialect."""
import json
import re
import uuid

import httpx

from harness.messages import Message, Reply, ToolCall, Usage
from harness.providers.base import ProviderError

# Thinking-only models can leak their reasoning into `content`, ending with </think> (Lesson 01).
LEAKED_THINKING = re.compile(r"^.*?</think>\s*", re.DOTALL)


class OllamaProvider:
    def __init__(self, model="qwen3:4b-instruct", url="http://localhost:11434",
                 num_ctx=8192, temperature=None, timeout=300):
        self.model = model
        self.url = url
        self.options = {"num_ctx": num_ctx}
        if temperature is not None:
            self.options["temperature"] = temperature
        self.http = httpx.Client(base_url=url, timeout=httpx.Timeout(timeout, connect=10))

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply:
        body = {
            "model": self.model,
            "messages": [to_ollama(m) for m in messages],
            "stream": False,
            "options": self.options,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]

        try:
            r = self.http.post("/api/chat", json=body)
        except httpx.ConnectError:
            raise ProviderError(f"cannot connect to Ollama at {self.url}. Is it running?") from None
        except httpx.TimeoutException:
            raise ProviderError("the model took too long to respond") from None
        if r.is_error:
            raise ProviderError(f"Ollama returned HTTP {r.status_code}: {r.text}")
        return from_ollama(r.json())


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
    usage = Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0))
    return Reply(Message("assistant", content, tool_calls=calls), stop, usage)
