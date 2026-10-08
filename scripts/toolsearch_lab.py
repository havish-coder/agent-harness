"""Lesson 50: what do thirty tools cost, and can a small model find the right one by searching?

Thirty invented tools (calendar, tickets, email, weather, files), each doing nothing but answering "ok", and ten requests that each need exactly one of them.

    all      every definition is in every request (tool search off)
    search   the definitions are held back; the prompt names the tools and the model has tool_search (tool search on)

For each request: did the first tool the model called (other than tool_search) match the one the request needs? How many tokens did the definitions cost? How many
model calls did it take? And did it search at all?

    python scripts/toolsearch_lab.py cost                      (no model) the tokens of 0, 10, 20, 30 tools
    python scripts/toolsearch_lab.py find [--runs 3] [--model qwen3:4b-instruct]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.agent import Agent  # noqa: E402
from harness.context.tokens import estimate_tokens  # noqa: E402
from harness.providers.factory import make_provider  # noqa: E402
from harness.tools.base import Tool, tool  # noqa: E402
from harness.tools.registry import ToolRegistry  # noqa: E402
from harness.toolsearch import catalog_text, make_search_tool, schema_tokens  # noqa: E402

SPECS = [
    ("calendar_create_event", "Create an event on the user's calendar.", {"title": "what the event is", "when": "date and time"}),
    ("calendar_list_events", "List the events on the user's calendar for a day.", {"day": "the day to list"}),
    ("calendar_delete_event", "Delete an event from the user's calendar.", {"title": "which event"}),
    ("calendar_find_free_time", "Find a free slot of a given length in the user's calendar.", {"minutes": "how long", "after": "earliest day"}),
    ("ticket_create", "Open a new ticket in the issue tracker.", {"title": "the ticket's title"}),
    ("ticket_comment", "Add a comment to a ticket.", {"ticket": "ticket number", "text": "the comment"}),
    ("ticket_close", "Close a ticket in the issue tracker.", {"ticket": "ticket number"}),
    ("ticket_assign", "Assign a ticket to a person.", {"ticket": "ticket number", "person": "who"}),
    ("ticket_search", "Search the issue tracker for tickets.", {"query": "words to look for"}),
    ("email_send", "Send an email.", {"to": "address", "body": "message text"}),
    ("email_search", "Search the user's mailbox.", {"query": "words to look for"}),
    ("email_draft", "Save an email draft without sending it.", {"to": "address", "body": "message text"}),
    ("email_archive", "Archive an email in the user's mailbox.", {"subject": "which email"}),
    ("weather_forecast", "Get the weather forecast for a city.", {"city": "which city", "day": "which day"}),
    ("weather_alerts", "List the severe weather alerts for a region.", {"region": "which region"}),
    ("files_compress_zip", "Compress a folder into a zip file.", {"folder": "which folder"}),
    ("files_convert_pdf", "Convert a document to PDF.", {"path": "which file"}),
    ("files_rename_batch", "Rename many files by a pattern.", {"folder": "where", "pattern": "the pattern"}),
    ("files_find_duplicates", "Find duplicate files in a folder.", {"folder": "where"}),
    ("contacts_lookup", "Look up a person's phone number or address.", {"name": "who"}),
    ("contacts_add", "Add a person to the contacts.", {"name": "who", "phone": "phone number"}),
    ("music_play", "Play a song or an album.", {"title": "what to play"}),
    ("music_queue", "Add a song to the play queue.", {"title": "which song"}),
    ("timer_start", "Start a countdown timer.", {"minutes": "how long"}),
    ("timer_cancel", "Cancel a running timer.", {"name": "which timer"}),
    ("reminder_set", "Set a reminder for a time.", {"text": "what to remind", "when": "when"}),
    ("reminder_list", "List the reminders that are set.", {}),
    ("translate_text", "Translate text into another language.", {"text": "what to translate", "language": "into which language"}),
    ("currency_convert", "Convert an amount of money between currencies.", {"amount": "how much", "from_to": "like USD to EUR"}),
    ("news_headlines", "Get today's news headlines on a topic.", {"topic": "which topic"}),
]
REQUESTS = [
    ("Put a dentist appointment on my calendar tomorrow at 3pm.", "calendar_create_event"),
    ("What is on my calendar on Friday?", "calendar_list_events"),
    ("Open a ticket titled 'login page crashes'.", "ticket_create"),
    ("Add the comment 'fixed in v2' to ticket 42.", "ticket_comment"),
    ("Close ticket 17.", "ticket_close"),
    ("Email sam@example.com saying the build is ready.", "email_send"),
    ("Will it rain in Lisbon tomorrow?", "weather_forecast"),
    ("Zip up the folder named reports.", "files_compress_zip"),
    ("Find me an hour free next Tuesday.", "calendar_find_free_time"),
    ("Assign ticket 9 to Priya.", "ticket_assign"),
]


def fake_tool(name: str, description: str, args: dict) -> Tool:
    """A tool that takes its arguments as strings and answers 'ok'. Built from a function with a real signature so the schema is real."""
    params = ", ".join(f"{a}: str" for a in args)
    namespace: dict = {}
    exec(f"def f({params}) -> str:\n    return 'ok'", namespace)           # noqa: S102 (a fixed, local template)
    f = namespace["f"]
    f.__doc__ = description + ("\n\nArgs:\n" + "\n".join(f"    {a}: {d}" for a, d in args.items()) if args else "")
    t = tool(read_only=True, deferrable=True, name=name)(f)
    return t


def registry(count: int = 30) -> ToolRegistry:
    return ToolRegistry([fake_tool(*s) for s in SPECS[:count]])


def cost() -> None:
    print(f"{'tools':>6} {'definitions, tokens':>20} {'names only (the catalog), tokens':>34}")
    for n in (0, 10, 20, 30):
        r = registry(n)
        print(f"{n:>6} {schema_tokens(list(r)):>20,} {estimate_tokens(catalog_text(list(r))):>34,}")


def run_once(request: str, expected: str, search: bool, model: str) -> dict:
    r = registry()
    r.add(make_search_tool(lambda: r)[0])
    if search:
        r.hold_back([t.name for t in r if t.deferrable])
    system = "You are a helpful agent. Use the tools to do what the user asks, then say what you did in one line."
    if search:
        system += "\n\n" + catalog_text([t for t in r if t.name in r.deferred])
    agent = Agent(make_provider("ollama", model, None), r, system, max_steps=6, stream=False)
    seen = []
    agent.on_event = lambda kind, data: seen.append(data.name) if kind == "tool_call" else None
    shown = schema_tokens([t for t in r if r.shown(t)])
    agent.run(request)
    used = [n for n in seen if n != "tool_search"]
    return {"right": bool(used) and used[0] == expected, "searched": "tool_search" in seen, "tokens": shown, "calls": len(seen), "first": used[0] if used else "(none)"}


def find(runs: int, model: str) -> None:
    print(f"{runs} runs per request, {len(REQUESTS)} requests, 30 tools, {model}\n")
    print(f"{'variant':<8} {'right tool first':>17} {'searched':>9} {'definition tokens':>18} {'tool calls':>11}")
    for variant, search in (("all", False), ("search", True)):
        rows = []
        for request, expected in REQUESTS:
            for _ in range(runs):
                rows.append(run_once(request, expected, search, model))
        n = len(rows)
        print(f"{variant:<8} {sum(r['right'] for r in rows):>14}/{n:<2} {sum(r['searched'] for r in rows):>6}/{n:<2} {sum(r['tokens'] for r in rows) / n:>18,.0f} "
              f"{sum(r['calls'] for r in rows) / n:>11.1f}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["cost", "find"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--model", default="qwen3:4b-instruct")
    args = ap.parse_args()
    cost() if args.task == "cost" else find(args.runs, args.model)


if __name__ == "__main__":
    main()
