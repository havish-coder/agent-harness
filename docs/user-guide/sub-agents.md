# Sub-agents

The agent's context window is the scarcest thing it has. A question like *"where do we apply tax, and to what?"* can mean fifteen file reads, and every one of them stays in the conversation for the rest of the chat. A **sub-agent** does that reading in a
conversation of its own and hands back a few lines. The main conversation pays for the report, not for the reading.

```text
> Which files use the tax rate, and what do they do with it?

● delegate(agent='explore', task='Find every use of TAX_RATE and apply_tax ...')
  ↳ explore: Find every use of TAX_RATE and apply_tax ...
      · grep(pattern='TAX_RATE|apply_tax')
      · read_file(path='project/shop/pricing.py')
      · read_file(path='project/shop/cart.py')
  ↳ explore finished: 3 tool calls, ~2,100 tokens, 19 s
  └ apply_tax (pricing.py:6) multiplies an amount by 1 + TAX_RATE (0.08). Cart.total (cart.py:19) calls it after the discount. Nothing else uses TAX_RATE.
```

## What a sub-agent is
A fresh agent with **its own conversation, its own context window and its own step limit**, started by the `delegate` tool with a task written by the main agent. It can't see the main conversation, so the task has to say everything. It returns its final answer
(cut to 4,000 characters) and a footer with what it cost: `(explore: 7 tool calls, ~9,100 tokens, 31 s)`.

Two come with the harness:

| Agent | Tools | For |
|---|---|---|
| `explore` | read-only: `list_dir`, `read_file`, `glob`, `grep`, `recall` | a question that needs many files read; it cannot change anything |
| `worker` | the main agent's own (edits, commands, web), minus the ones below | a self-contained job you want kept out of the main conversation |

`/agents` lists the definitions available, and where each came from.

## What it shares with the main agent, and what it doesn't
**Shared** (so a sub-agent can never do what the main agent couldn't):
- the **permissions**: the same mode and rules. In [plan mode](plan-mode.md) a `worker` can read and nothing more; an edit asks you just as it would from the main agent; an `explore` agent has no editing tools at all;
- your **approvals** (you are asked about its edits, and you see which tool wants to run), the **hooks** (a `pre_tool_use` hook sees its calls), the **limits and costs** of the session, and the **undo** history (`/undo` takes back a worker's edits like any other);
- the **record of untrusted content**: if a sub-agent reads something you don't trust, the whole session counts as having read it, and **its report comes back fenced as untrusted** so the main agent treats it as information, not as instructions ([untrusted content](untrusted-content.md)).

**Its own:** the conversation, the system prompt (its definition, the untrusted-content rule, your project notes, a short listing of the workspace), the context window, the step limit.

**Never given** to a sub-agent: `delegate` (a sub-agent can't start sub-agents: depth is one), `ask_user`, `exit_plan_mode`, `todo_write`, and the tools that write things down for later chats (`remember`, `forget`, `update_progress`).

The sub-agent's messages are **not** saved in the chat: the saved chat is the main conversation, with the report in it.

## Your own agents
A Markdown file with a short header, in `~/.harness/agents/` (yours) or `<project>/.harness/agents/` (the project's):

```markdown
---
name: reviewer
description: reads a change and lists what could go wrong; cannot edit
tools: read_file, grep, glob        # read-only | all | a list of tool names
max_steps: 10                       # 1 to 30
model: inherit                      # or a model name, for a cheaper or a bigger one
---
You review code. Read what you are given, then list the three most likely problems, each with the file and line.
```

- A project's definitions are read **only in a folder you [trust](untrusted-content.md)**: a definition is instructions for a model, and a cloned repository must not get to write them. A project can't replace a built-in agent.
- `/agents reload` reads them again (after `/trust`).
- Names use `a-z`, `0-9` and `-`.

## When the agent uses it
A sentence in the system prompt says to hand a question that needs many files read to `explore`. A small model uses `delegate` less often than you might hope: see what it measured. You can always ask: *"use the explore agent to find ..."*.

## What it measured
Four questions about a 14-module package with planted facts ("What is the value of RETRY_LIMIT in the inventory package?"), three runs each, `qwen3:4b-instruct` (`scripts/agents_lab.py answers`):

| variant | right answers | parent's conversation at the end (tokens) | parent's tool calls | delegated | tokens used in all | stopped early |
|---|---|---|---|---|---|---|
| `inline`: no sub-agents | 12/12 | 3,389 | 2.5 | (no tool) | 9,189 | 0/12 |
| `rule`: `delegate` offered, and the prompt says when | 12/12 | 3,739 | 2.6 | **0/12** | 10,210 | 0/12 |
| `forced`: the harness delegates the question for it | 12/12 | **2,435** | 1.0 | 12/12 | 8,105 | 0/12 |

Handing the reading to `explore` kept every answer right and left the main conversation about 30% smaller. But this small model, told when to delegate, **never chose to** (0 of 12): it found each fact with a `grep` in two or three calls, which for these questions was the cheaper path anyway. Ask for it when you want it: *"use the explore agent to find ..."*.

## Setting
`"subagents": false` removes `delegate` and its sentence in the prompt. A project may set it.
