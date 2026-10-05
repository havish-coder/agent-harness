"""Lesson 03: one tool-calling round trip, done by hand so every step is visible.

Run:   python scripts/tool_call_by_hand.py
       python scripts/tool_call_by_hand.py "What time is it, and how many TODOs are in notes.txt?"
       python scripts/tool_call_by_hand.py "What is 2 + 2?"

There is deliberately no loop here. Lesson 06 turns these steps into the agent loop.
"""
import datetime
import json
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

MODEL = "qwen3:4b-instruct"
URL = "http://localhost:11434/api/chat"
WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"

# ── 1. Describe the tools to the model (JSON Schema) ────────────────────────
# The model never sees our Python functions, only these descriptions.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the user's workspace and return its contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the workspace, e.g. notes.txt"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current local date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ── 2. The real Python functions behind the tools ───────────────────────────

def read_file(path):
    # WARNING: no security yet. "../" paths can escape the workspace. Fixed in Lesson 18.
    return (WORKSPACE / path).read_text(encoding="utf-8")


def get_current_time():
    return datetime.datetime.now().strftime("%A %d %B %Y, %H:%M")


FUNCTIONS = {"read_file": read_file, "get_current_time": get_current_time}


def call_model(messages):
    body = {"model": MODEL, "messages": messages, "tools": TOOLS, "stream": False, "options": {"num_ctx": 4096}}
    r = httpx.post(URL, json=body, timeout=httpx.Timeout(300, connect=10))
    r.raise_for_status()
    return r.json()["message"]


def show(title, obj):
    print(f"\n── {title} " + "─" * (60 - len(title)))
    print(obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False))


question = sys.argv[1] if len(sys.argv) > 1 else "How many TODOs are in notes.txt?"
messages = [{"role": "user", "content": question}]
show("USER", question)

# ── STEP 1: send the question + tool descriptions ───────────────────────────
reply = call_model(messages)
show("STEP 1 · model replied (raw message)", reply)
messages.append(reply)  # the assistant's tool request MUST stay in the history

if not reply.get("tool_calls"):
    show("No tool needed: that was the final answer", reply["content"])
    sys.exit()

# ── STEP 2: the HARNESS runs each requested tool ────────────────────────────
for call in reply["tool_calls"]:
    name, args = call["function"]["name"], call["function"]["arguments"]
    try:
        result = FUNCTIONS[name](**args)
    except Exception as e:  # unknown tool, bad arguments, missing file...
        result = f"Error: {type(e).__name__}: {e}"  # errors go back to the model as text
    show(f"STEP 2 · harness ran {name}({json.dumps(args)})", result)
    messages.append({"role": "tool", "tool_name": name, "content": result})

# ── STEP 3: send everything back so the model can use the results ──────────
final = call_model(messages)
show("STEP 3 · model replied", final)
if final.get("tool_calls"):
    print("\nThe model wants ANOTHER tool call. Handling that needs a loop (Lesson 06).")
