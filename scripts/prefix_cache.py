"""Lesson 37: does the order of the system prompt's sections change how much Ollama has to read again?

Ollama keeps the tokens of the last request in memory and, on the next one, re-reads only what comes after
the first token that differs. This script sends the real system prompt and the real tool definitions three
ways and prints how many prompt tokens the server had to evaluate each time:

    stable first    role, rules, environment, files   (what the harness does)
    volatile first  environment, role, rules, files   (the same text, the changing line at the start)

For each order it changes only the date line in the environment section, and then only the user's question.

    python scripts/prefix_cache.py [--runs 3] [--model qwen3:4b-instruct]

Needs Ollama running with the model pulled. Prints a table; nothing is written.
"""
import argparse
import datetime
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.context.prompt import environment_text  # noqa: E402
from harness.messages import Message  # noqa: E402
from harness.providers.ollama import OllamaProvider  # noqa: E402
from harness.security.taint import SYSTEM_RULE  # noqa: E402
from harness.session import ROLE, WORKSPACE_HEADER  # noqa: E402
from harness.tools import default_tools  # noqa: E402
from harness.tools.fs import workspace_snapshot  # noqa: E402
from harness.workspace import Workspace  # noqa: E402


def prompt(order: str, ws: Workspace, day: datetime.date) -> str:
    env = environment_text(ws.root, "bash", day, git=False)
    files = f"{WORKSPACE_HEADER}\n{workspace_snapshot(ws)}"
    parts = [ROLE, SYSTEM_RULE, env, files] if order == "stable first" else [env, ROLE, SYSTEM_RULE, files]
    return "\n\n".join(parts)


def send(provider: OllamaProvider, system: str, question: str, tools: list[dict]) -> dict:
    messages = [Message.system(system), Message.user(question)]
    r = provider.http.post("/api/chat", json=provider.body(messages, tools, stream=False))
    r.raise_for_status()
    data = r.json()
    return {"read": data.get("prompt_eval_count", 0), "ms": data.get("prompt_eval_duration", 0) / 1e6}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--model", default="qwen3:4b-instruct")
    args = ap.parse_args()
    provider = OllamaProvider(args.model, num_ctx=8192, num_predict=1)
    root = Path(__file__).resolve().parents[1] / "workspace"
    ws = Workspace(root if root.exists() else Path(tempfile.mkdtemp()))
    tools = [t.schema() for t in default_tools(ws)]
    start = datetime.date(2026, 10, 1)
    print(f"model {args.model}; {args.runs} runs each; 'reported' = the prompt_eval_count the server returns; the time is what shows the cache\n")
    print(f"{'order':<15} {'what changed':<22} {'reported':>9} {'median ms':>10} {'range ms':>13}")
    for order in ("stable first", "volatile first"):
        rows: dict[str, list[dict]] = {"the date": [], "only the question": []}
        for i in range(args.runs):
            day = start + datetime.timedelta(days=2 * i)
            send(provider, prompt(order, ws, day), "What is in notes.txt?", tools)                    # warm up: this is what the server remembers
            rows["the date"].append(send(provider, prompt(order, ws, day + datetime.timedelta(days=1)),
                                         "What is in notes.txt?", tools))
            rows["only the question"].append(send(provider, prompt(order, ws, day + datetime.timedelta(days=1)),
                                                  "How many files are here?", tools))
        for what, results in rows.items():
            times = [r["ms"] for r in results]
            print(f"{order:<15} {what:<22} {statistics.mean(r['read'] for r in results):>9,.0f} "
                  f"{statistics.median(times):>10,.0f} {min(times):>6,.0f}-{max(times):<6,.0f}")
    system = prompt("stable first", ws, start)
    print(f"\nsystem prompt ~{len(system):,} characters; the tool definitions come after it in qwen3's chat template")


if __name__ == "__main__":
    main()
