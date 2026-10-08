# Tool search

Every tool the agent can call is described in **every** request: its name, what it does, each argument. This harness's tools take about 2,600 tokens that way, a third of the 8,192-token window of the small model it is built for. A server that adds forty more would take the rest.
But to answer *"what's in this folder?"* the agent needs three descriptions, not forty.

**Tool search** holds the descriptions of rarely used tools back. The prompt gives only their **names**, and the agent calls `tool_search("what I want to do")` to find the tool it needs. The best few matches are loaded, and from the next request on they are described like any other tool.

```text
> Remember that I prefer tabs

● tool_search(query='save a note')
  └ Loaded: remember, recall. You can call them now.
    - remember: Save a note for later chats in this project.
        remember(title: string, description: string, kind: "user"|"feedback"|"project"|"reference", text: string)
● remember(title='Indentation', description='The user prefers tabs', kind='user', text='...')
```

## What is held back
Tools that declare themselves **deferrable** (rarely used): `remember`, `recall`, `forget` (saved notes), `update_progress` (the journal), `web_fetch`, `task_output` and `task_stop`. The core tools (read, search, edit, run commands) and the ones the prompt's rules refer to by name (`todo_write`, `ask_user`, `delegate`,
`use_skill`) are always shown. `/tools` marks the held-back ones: `held back: found with tool_search`.

## When it is on
| `"tool_search"` | |
|---|---|
| `"auto"` (default) | on **only when the definitions take more than 15% of the model's window**: always in the 8K window of a small local model, never in a 200K one |
| `"on"` | always |
| `"off"` | never: every definition in every request |

A project may choose the setting.

## How the search works
The plainest thing that works: the words of your query against the **words of each held-back tool's name (worth three) and of its description (worth one)**, with a rough stem (`fetching` finds `fetch`). The best five are loaded. No model call, no embeddings: it is cheap, it gives the same answer
every time, and you can read why. If nothing matches, the answer lists the names of the tools that exist.

Calling a held-back tool before loading it is an error that says to search first.

## What it doesn't change
**Safety.** Held back or shown, a tool is judged by the same [permission rules](permissions.md), [hooks](hooks.md) and sandbox. Only what the model is *told* changes.

**The prompt.** The names stay in the prompt after a tool is loaded, so the start of the prompt doesn't change and the model server's cache isn't thrown away.

**Resuming.** A resumed chat has the tools it found earlier again (`/resume` reads them from the conversation); `/reset` starts a new chat that has found none.

## What it measured
TOOLSEARCH_RESULT
