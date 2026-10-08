"""Lesson 50: tool search. Show the model a tool's definition only when it needs the tool.

Every tool the model can call is described in every request: its name, what it does, each argument. The definitions of this harness's tools took about 1,700 tokens in v0.6 and about 2,600 now, in a window of 8,192.
A server that adds forty tools (Lesson 51) would take the rest. But a model doesn't need forty descriptions to answer "what's in this folder?": it needs the three it will use.

The fix is two-sided:
  * a tool that can wait is marked `deferrable`. While tool search is active (always, or when the definitions take more than 15% of the window), the model is not shown such a tool's definition. The prompt gives
    it only the names ("More tools, found with tool_search: web_fetch, remember, recall ...");
  * the model calls `tool_search(query)`. The harness matches the query against the names and descriptions of the tools being held back, returns the best few with a line each and their signatures, and **loads**
    them: from the next request on, their definitions are included. Calling a held-back tool that hasn't been loaded is an error that says to search first.

The search is the plainest thing that works: words of the query against words of the name (counted three times) and of the description. No model call, no embeddings: it is cheap, deterministic, and can be read.

Which tools wait is not a safety decision. Held back or not, a tool is judged by the same permission rules, hooks and sandbox; deferring only changes what the model is told. What it does cost is a round trip, and
the chance that a small model never searches for a tool it should have used: the lab measures that.
"""
import re
from dataclasses import dataclass

from harness.context.tokens import estimate_tokens
from harness.tools.base import Tool, tool
from harness.tools.registry import signature

TOOL_SHARE = 0.15            # "auto": hold tools back when their definitions take more than this share of the window
CATALOG_TOKENS = 250         # what the prompt spends on the names of the tools held back
MAX_RESULTS = 5
WORD = re.compile(r"[a-z0-9]+")


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[:-len(suffix)]
    return word


def words(text: str) -> list[str]:
    return [stem(w) for w in WORD.findall(text.lower().replace("_", " ")) if len(w) > 1]


@dataclass
class Match:
    tool: Tool
    score: int


def search(tools: list[Tool], query: str, limit: int = MAX_RESULTS) -> list[Match]:
    """The tools whose name or description share words with the query, best first. A word in the name counts three; in the description, one."""
    wanted = list(dict.fromkeys(words(query)))
    scored = []
    for t in tools:
        name_words, desc_words = set(words(t.name)), set(words(t.description.split("\n\n")[0]))
        score = sum(3 if w in name_words else 1 if w in desc_words else 0 for w in wanted)
        if score:
            scored.append(Match(t, score))
    return sorted(scored, key=lambda m: (-m.score, m.tool.name))[:limit]


def schema_tokens(tools: list[Tool]) -> int:
    import json
    return estimate_tokens(json.dumps([t.schema() for t in tools]))


def catalog_text(held: list[Tool], max_tokens: int = CATALOG_TOKENS) -> str:
    """The prompt's note about the tools not shown: their names, cut to a budget."""
    if not held:
        return ""
    head = "More tools exist but are not shown. To use one, find it with tool_search(query) first: "
    names, used = [], estimate_tokens(head)
    for t in held:
        if used + estimate_tokens(t.name) + 1 > max_tokens:
            names.append(f"and {len(held) - len(names)} more")
            break
        names.append(t.name)
        used += estimate_tokens(t.name) + 1
    return head + ", ".join(names) + "."


def make_search_tool(get_registry) -> list[Tool]:
    """`tool_search(query)`: find held-back tools and load them. Offered only while some are held back. `get_registry()` returns the agent's registry."""

    @tool(read_only=True, concurrency_safe=False, enabled=lambda: bool(get_registry().held_back()))
    def tool_search(query: str) -> str:
        """Find tools that are not shown to you yet, and load them so you can call them next. Describe what you want to do, in a few words.

        Args:
            query: what you want a tool for, e.g. "fetch a web page" or "save a note".
        """
        registry = get_registry()
        held = registry.held_back()
        found = search(held, query)
        if not found:
            names = ", ".join(t.name for t in held)
            return f"No tool matched '{query}'. The tools not shown: {names}. Try other words, or one of those names."
        registry.load([m.tool.name for m in found])
        lines = [f"- {m.tool.name}: {m.tool.description.split(chr(10))[0]}\n    {signature(m.tool)}" for m in found]
        return "Loaded: " + ", ".join(m.tool.name for m in found) + ". You can call them now.\n" + "\n".join(lines)

    return [tool_search]
