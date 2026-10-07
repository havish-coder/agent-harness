"""Lesson 38: what does clearing an old result cost the server's prompt cache?

Clearing changes a message near the start of the conversation, so the server must read everything after it
again. This sends a conversation with three file reads to Ollama three ways and times the prompt read:

    same        the identical conversation again (the cache is warm)
    cleared     the oldest read replaced by its note
    new result  one more read added at the end (the usual growth)

    python scripts/micro_cost.py [--runs 5] [--model qwen3:4b-instruct]

Needs Ollama running with the model pulled. Prints a table; nothing is written.
"""
import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.context.micro import clear_old_results  # noqa: E402
from harness.messages import Message, ToolCall  # noqa: E402
from harness.providers.ollama import OllamaProvider  # noqa: E402
from harness.tools import default_tools  # noqa: E402
from harness.workspace import Workspace  # noqa: E402


def result_text(n: int, rows: int = 90) -> str:
    return "\n".join(f"{i:>5}\trow {i:03}: value {(i * 7919 + n * 104729) % 100000:05} status ok" for i in range(rows))


def conversation(reads: int, seed: int = 0) -> list[Message]:
    messages = [Message.system("You are a helpful agent. Use tools to inspect the workspace."), Message.user("Read the files.")]
    for n in range(reads):
        call = ToolCall(f"c{n}", "read_file", {"path": f"part{n}.txt"})
        messages += [Message("assistant", "", tool_calls=[call]), Message.tool_result(call, result_text(n + seed))]
    return messages


def timed(provider: OllamaProvider, messages: list[Message], tools: list[dict]) -> float:
    r = provider.http.post("/api/chat", json=provider.body(messages, tools, stream=False))
    r.raise_for_status()
    return r.json().get("prompt_eval_duration", 0) / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--model", default="qwen3:4b-instruct")
    args = ap.parse_args()
    provider = OllamaProvider(args.model, num_ctx=8192, num_predict=1)
    tools = [t.schema() for t in default_tools(Workspace(Path(".")))]
    rows: dict[str, list[float]] = {"same": [], "cleared": [], "new result": []}
    first = int(time.time()) % 100_000                                # new file contents every run, and every time this script runs:
    for run in range(args.runs):                                      # the server remembers earlier prompts, which would answer this one
        seed = first + 10 * run
        base = conversation(2, seed)
        timed(provider, base, tools)                                  # warm: the server remembers this
        rows["same"].append(timed(provider, base, tools))
        timed(provider, base, tools)
        cleared = conversation(2, seed)
        clear_old_results(cleared, {"read_file"}, keep_recent=1)
        rows["cleared"].append(timed(provider, cleared, tools))
        timed(provider, base, tools)
        rows["new result"].append(timed(provider, conversation(3, seed), tools))
    print(f"model {args.model}; {args.runs} runs; time to read the prompt (median, ms)\n")
    for name, times in rows.items():
        print(f"{name:<12} {statistics.median(times):>8,.0f}   range {min(times):,.0f}-{max(times):,.0f}")


if __name__ == "__main__":
    main()
