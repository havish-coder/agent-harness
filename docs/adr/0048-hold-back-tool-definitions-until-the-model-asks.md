# 0048. Hold back the definitions of rarely used tools until the model asks for them

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
A tool's definition (name, description, arguments) is part of every request. Measured with `/context`'s estimator, the tools of v0.6 took about **1,700 tokens**; with the three tools and prompt rules Module 7 added (todo, asking, delegating) and the background-task tools,
about **2,600**: a third of an 8,192-token window, on every request. That is paid before the user has said anything, and it will get worse: a connected server (Lesson 51) can add dozens.

Measured (`scripts/toolsearch_lab.py`): thirty invented tools cost **2,014 tokens** as definitions and **140** as names; and what a 4B model does when it has to search first: thirty invented tools, ten requests that each need one, three runs each, `qwen3:4b-instruct`:

| variant | right tool first | searched | definitions sent (tokens) | tool calls (mean) |
|---|---|---|---|---|
| `all`: every definition in every request | 30/30 | 0/30 | 2,014 | 1.0 |
| `search`: held back, found with `tool_search` | **23/30** | 23/30 | **95** | 1.5 |
| `search`, first version (the bug below) | 0/30 | 20/30 | 95 | 2.1 |

Every run that searched then called the right tool; the seven misses never searched.

## Options
1. **Show everything**: always available, costs the window.
2. **Fewer, bigger tools**: fewer definitions, but each tool does more and takes more arguments (the shell is one tool because that works; it is not a design to extend).
3. **Hold back what is rarely used, behind a search**: pay a round trip when a held-back tool is needed.
4. **Choose the tools for the request with a model call** (a router): accurate, but a model call before every request.

## Decision
Option 3 (`harness/toolsearch.py`).

- **`Tool.deferrable`** marks a tool that can wait (the notes tools, the journal tool, `web_fetch`, the task tools). **Whether it waits is the session's decision**: `tool_search: "auto"` (default) holds them back only when the definitions take more than 15% of the window; `"on"` always; `"off"` never.
  The tools the prompt's rules name (`todo_write`, `ask_user`, `delegate`, `use_skill`) and the core file and shell tools are never deferrable: a rule that says "call X" can't refer to a tool that isn't there.
- **`tool_search(query)`** (read-only, offered only while something is held back) scores the held-back tools by the words of the query against the **words of the name (worth 3) and of the description (worth 1)**, with a rough stem, returns the best five with their signatures, and **loads** them: their definitions are included from the next request.
  No model call and no embeddings: deterministic, free, readable.
- **The prompt names the held-back tools** (`more tools`, within 250 tokens) and keeps naming them after they are loaded, so the start of the prompt never changes and the server's cache isn't lost.
- **Calling a held-back tool that hasn't been loaded is an error** that says to search first, not an automatic load: the model has seen no definition, and its arguments would be a guess.
- **Loaded tools are rebuilt from the conversation** after a resume or a rewind (a call to the tool, or a `tool_search` result saying `Loaded: ...`); `/reset` forgets them.
- **It is not a safety feature.** The same permission rules, hooks and sandbox judge a call whether or not its definition was shown.

## Consequences
- In the default small window about 700 tokens come back per request. On the lab's thirty tools the definitions went from 2,014 tokens to 95, for 23 of 30 right first calls instead of 30 of 30: the cost of deferral is the model that doesn't search (7 runs answered without a tool).
- **The tool list is rebuilt before every model call**, not once per request. The first version built it once, so a tool `tool_search` had just loaded was not sent until the user's next message: the model was told "you can call them now", wasn't shown them, and searched again (0 of 30). A scripted test model doesn't care what it is sent, so the tests passed; a test now checks the definitions the model receives.
- A small model must decide to search. A tool that is held back and never searched for is a tool that is never used: this is the cost, and it is why the always-visible set is the one the prompt's rules mention.
- Search quality is the words of the tool authors: a tool whose description never says what it is for is hard to find. Lesson 51's servers write their own descriptions, which are untrusted text; deferral means they enter the conversation only when searched for.
- The 15% threshold is a judgment, not a measurement: below it everything is shown and nothing changes; above it, held back. The `"on"` and `"off"` settings exist for when it is wrong for a model.
