"""Lesson 07: a terminal chat app around the agent.

Run:  harness                               (after `pip install -e .`)
      python -m harness.cli --model qwen3:4b --workspace C:\\some\\folder
"""
import argparse
import os
import sys
from pathlib import Path

from harness.agent import Agent
from harness.providers.base import ProviderError
from harness.providers.ollama import OllamaProvider
from harness.tools.fs import make_fs_tools, workspace_snapshot

# Short and direct works best for small models (see course/07-first-tools-and-repl.md).
SYSTEM_PROMPT = """You are a helpful agent. Use tools to inspect the workspace; never guess file contents.
Explore folders with list_dir before saying something doesn't exist.
Paths are relative to the workspace root. Be concise.

Workspace files (snapshot at session start; may have changed since):
{snapshot}"""

DIM, CYAN, BOLD, RESET = "\033[2m", "\033[36m", "\033[1m", "\033[0m"


def show_event(kind, data):
    """Print the agent's actions as they happen."""
    if kind == "tool_call":
        args = ", ".join(f"{k}={v!r}" for k, v in data.arguments.items())
        print(f"{CYAN}  → {data.name}({args}){RESET}")
    elif kind == "tool_result":
        _, result = data
        preview = result if len(result) <= 300 else result[:300] + " …"
        print(DIM + "    " + preview.replace("\n", "\n    ") + RESET)


def main():
    p = argparse.ArgumentParser(description="Chat with a tool-using agent.")
    p.add_argument("--model", default="qwen3:4b-instruct")
    p.add_argument("--workspace", default="workspace", help="folder the agent can look at")
    p.add_argument("--max-steps", type=int, default=10)
    args = p.parse_args()

    if os.name == "nt":
        os.system("")  # makes old Windows consoles understand the colour codes above
    sys.stdout.reconfigure(encoding="utf-8")

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        sys.exit(f"workspace folder not found: {workspace}")

    system_prompt = SYSTEM_PROMPT.format(snapshot=workspace_snapshot(workspace))
    agent = Agent(OllamaProvider(model=args.model), make_fs_tools(workspace), system_prompt,
                  max_steps=args.max_steps, on_event=show_event)
    print(f"{BOLD}Agent harness{RESET} · model {args.model} · workspace {workspace}")
    print(f"{DIM}Commands: /reset (forget the conversation)  /bye (quit)  ·  Ctrl+C cancels a running task{RESET}")

    while True:
        try:
            user = input(f"\n{BOLD}you>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user == "/bye":
            break
        if user == "/reset":
            agent.reset()
            print(f"{DIM}(conversation cleared){RESET}")
            continue

        before = agent.usage.input_tokens, agent.usage.output_tokens
        try:
            answer = agent.run(user)
        except KeyboardInterrupt:
            print(f"\n{DIM}(cancelled){RESET}")
            continue
        except ProviderError as e:
            print(f"error: {e}")
            continue
        print(f"\n{BOLD}agent>{RESET} {answer}")
        used_in = agent.usage.input_tokens - before[0]
        used_out = agent.usage.output_tokens - before[1]
        print(f"{DIM}  [{used_in} input + {used_out} output tokens]{RESET}")


if __name__ == "__main__":
    main()
