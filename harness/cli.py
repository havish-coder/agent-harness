"""Lessons 07-16: a terminal chat app around the agent.

Run:  harness                               (after `pip install -e .`)
      python -m harness.cli --model qwen3:4b --workspace C:\\some\\folder
"""
import argparse
import os
import sys
from pathlib import Path

from harness.agent import Agent
from harness.providers.base import ProviderError
from harness.providers.factory import PROVIDERS, make_provider
from harness.tools import default_tools
from harness.tools.fs import workspace_snapshot
from harness.workspace import Workspace

# Short and direct works best for small models (see course/07-first-tools-and-repl.md).
SYSTEM_PROMPT = """You are a helpful agent. Use tools to inspect the workspace; never guess file contents.
Find files with glob, search inside them with grep, explore folders with list_dir.
To find where something is defined or used, grep for a likely word (e.g. grep 'timeout' to find a timeout setting).
Paths are relative to the workspace root. Be concise.

Workspace files (snapshot at session start; may have changed since):
{snapshot}"""

DIM, CYAN, BOLD, YELLOW, RESET = "\033[2m", "\033[36m", "\033[1m", "\033[33m", "\033[0m"


class TerminalApprover:
    """Asks before any tool call that can change things. 'a' = always allow this tool."""

    def __init__(self, auto_approve: bool = False):
        self.auto_approve = auto_approve
        self.always: set[str] = set()   # tool names allowed for the rest of the session

    def __call__(self, call, tool) -> bool:
        if self.auto_approve or tool.name in self.always:
            return True
        warning = " (may destroy data)" if tool.is_destructive(call.arguments) else ""
        print(f"{YELLOW}  ? {tool.name} wants to run{warning}{RESET}")
        if tool.preview:
            try:
                print(DIM + "    " + tool.preview(**call.arguments).replace("\n", "\n    ") + RESET)
            except Exception as e:
                print(f"{DIM}    (no preview: {e}){RESET}")
        while True:
            answer = input(f"{YELLOW}    allow? [y]es / [n]o / [a]lways for {tool.name}: {RESET}").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no", ""):
                return False
            if answer in ("a", "always"):
                self.always.add(tool.name)
                return True


class Printer:
    """Prints the agent's events as they happen, including streamed text (Lesson 16)."""

    def __init__(self):
        self.mid_line = False      # inside a streamed line that hasn't ended yet
        self.current = ""          # text streamed for the reply in progress
        self.last_streamed = ""    # text streamed for the last complete reply

    def end_line(self):
        if self.mid_line:
            print()
            self.mid_line = False

    def __call__(self, kind, data):
        if kind == "thinking_delta":
            if not self.mid_line:
                print(f"{DIM}  (thinking) ", end="")
            print(f"{DIM}{data}{RESET}", end="", flush=True)
            self.mid_line = True
        elif kind == "text_delta":
            if not self.current:
                self.end_line()
                print(f"\n{BOLD}agent>{RESET} ", end="")
            print(data, end="", flush=True)
            self.current += data
            self.mid_line = True
        elif kind == "model_reply":
            self.end_line()
            self.last_streamed, self.current = self.current, ""
        elif kind == "tool_call":
            self.end_line()
            args = ", ".join(f"{k}={v!r}" for k, v in data.arguments.items())
            print(f"{CYAN}  → {data.name}({args}){RESET}")
        elif kind == "tool_denied":
            print(f"{DIM}    (denied){RESET}")
        elif kind == "tool_result":
            _, result = data
            preview = result if len(result) <= 300 else result[:300] + " …"
            print(DIM + "    " + preview.replace("\n", "\n    ") + RESET)

    def answer(self, text: str):
        """Print the final answer, unless it was already streamed to the screen."""
        self.end_line()
        if text.strip() != self.last_streamed.strip():
            print(f"\n{BOLD}agent>{RESET} {text}")
        self.last_streamed = ""


def main():
    p = argparse.ArgumentParser(description="Chat with a tool-using agent.")
    p.add_argument("--provider", default="ollama", choices=PROVIDERS, help="where the model runs")
    p.add_argument("--model", default=None, help="model name (default for ollama: qwen3:4b-instruct)")
    p.add_argument("--base-url", default=None, help="override the provider's server address")
    p.add_argument("--workspace", default="workspace", help="folder the agent can look at")
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--yes", action="store_true",
                   help="approve every tool call without asking (only for throwaway folders)")
    p.add_argument("--no-stream", action="store_true", help="wait for whole replies instead of streaming")
    p.add_argument("--think", action="store_true", help="for thinking models: show their reasoning separately")
    args = p.parse_args()

    if os.name == "nt":
        os.system("")  # makes old Windows consoles understand the colour codes above
    sys.stdout.reconfigure(encoding="utf-8")

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        sys.exit(f"workspace folder not found: {workspace}")
    ws = Workspace(workspace)

    system_prompt = SYSTEM_PROMPT.format(snapshot=workspace_snapshot(ws))
    printer = Printer()
    try:
        provider = make_provider(args.provider, args.model, args.base_url, think=True if args.think else None)
    except ProviderError as e:
        sys.exit(f"error: {e}")
    agent = Agent(provider, default_tools(ws), system_prompt, max_steps=args.max_steps, on_event=printer,
                  approve=TerminalApprover(auto_approve=args.yes), stream=not args.no_stream)
    print(f"{BOLD}Agent harness{RESET} · {args.provider} · model {provider.model} · workspace {workspace}")
    print(f"{DIM}Commands: /reset (forget the conversation)  /bye (quit)  ·  Ctrl+C cancels a running task{RESET}")
    if args.yes:
        print(f"{YELLOW}--yes: every tool call runs without asking.{RESET}")

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
            ws.forget_reads()   # the model no longer has earlier reads in its context
            print(f"{DIM}(conversation cleared){RESET}")
            continue

        before = agent.usage.input_tokens, agent.usage.output_tokens
        try:
            answer = agent.run(user)
        except KeyboardInterrupt:
            printer.end_line()
            print(f"\n{DIM}(cancelled){RESET}")
            continue
        except ProviderError as e:
            printer.end_line()
            print(f"error: {e}")
            continue
        printer.answer(answer)
        used_in = agent.usage.input_tokens - before[0]
        used_out = agent.usage.output_tokens - before[1]
        print(f"{DIM}  [{used_in} input + {used_out} output tokens]{RESET}")


if __name__ == "__main__":
    main()
