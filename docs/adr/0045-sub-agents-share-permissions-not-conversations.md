# 0045. Sub-agents share the parent's permissions, taint and limits, and not its conversation

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
Reading is what fills a context window (Lesson 36): a question that needs fifteen files read leaves fifteen results in the conversation for good. A sub-agent, a second agent loop with a conversation of its own, can do the reading and return a short
report. Measured (`scripts/agents_lab.py context`): eight modules, 8,381 tokens of source; after the main agent read them itself its conversation held about **15,200 tokens**, after delegating the same job about **2,100**: the window of the model
this project is built for is 8,192.

A second agent is also a second place for everything to go wrong: a loop the permission rules don't cover, a conversation the hooks don't see, a place to read untrusted content without the session finding out, a cost the limits don't count.

## Options
1. **No sub-agents**: one conversation; the context lesson's clearing and summaries are the only relief.
2. **A fully separate agent** (own permissions, own approver): simple to reason about locally; but then it needs its own copy of every rule, and any gap is an escape.
3. **A sub-agent that shares the session's safety state and has its own conversation.**

## Decision
Option 3 (`harness/agents.py`, `Session.delegate`).

- **Shared, by passing the same objects**: `Permissions` (mode, rules, and the taint record), the approver, the `Hooks`, the limit check, the cost tracker and the file history. Not copies: there is nothing to keep in step, and no copy to forget to update.
  So a sub-agent can't do what its parent can't: in plan mode its edits are refused; an edit asks the same way; a `pre_tool_use` hook sees its calls; what it reads from an untrusted source taints the session; what it spends counts against the same limits; `/undo` takes back its edits.
- **Its own**: the messages, the system prompt (the definition's text, the untrusted-content rule, the project's notes, a 30-line workspace listing), the context budget (a fresh `ContextBudget`, so it clears and summarises on its own), the step limit (12 by default, at most 30).
- **Depth one and a smaller toolbox.** A sub-agent never gets `delegate`, `ask_user`, `exit_plan_mode`, `todo_write`, `remember`, `forget` or `update_progress`: starting more agents, talking to the user, and writing down state for later are the parent's. `explore` gets only tools
  whose read-only flag is a constant `True` (a flag that depends on the arguments, like the shell's, doesn't count): a tool added later that is read-only qualifies, one that is not doesn't.
- **`delegate` is read-only for permissions.** It changes nothing itself: every call the sub-agent makes is decided by the permission layer. Asking about the delegation as well would be a second question about one thing, and would deny `explore` in plan mode, where it is most useful.
- **A report from an agent that read something untrusted is fenced.** The taint record is compared before and after the run; if it grew, the report comes back inside an `<untrusted>` fence naming the sub-agent. A report is model-written text derived from what the agent read, so it carries the same risk.
- **Definitions are Markdown files**, like commands and styles: built-ins first, then `~/.harness/agents/`, then the project's, **only in a trusted folder**, never replacing a built-in. A definition is instructions for a model, so it has the standing of `HARNESS.md`, not of a command.
- **The conversation stays out of the chat**: a sub-agent's messages aren't written to the saved chat or counted as turns; its tool calls and model replies are counted (limits, costs, the audit log, which labels them with the agent's name) and shown on screen as short indented lines.
- **Sequential**: `delegate` isn't parallel-safe in this version (the terminal's display and the approver aren't thread-safe). Fan-out is the obvious next step.

## Consequences
- The main conversation pays for the report and not the reading: measured above. The sub-agent still pays in its own window: a job that overflows a small window overflows it there too, and what it can keep of what it read is whatever fits its own context.
- A small model rarely chooses to delegate. Four questions about a 14-module package with planted facts ("What is the value of RETRY_LIMIT in the inventory package?"), three runs each, `qwen3:4b-instruct` (`scripts/agents_lab.py answers`):

| variant | right answers | parent's conversation at the end (tokens) | parent's tool calls | delegated | tokens used in all | stopped early |
|---|---|---|---|---|---|---|
| `inline`: no sub-agents | 12/12 | 3,389 | 2.5 | (no tool) | 9,189 | 0/12 |
| `rule`: `delegate` offered, and the prompt says when | 12/12 | 3,739 | 2.6 | **0/12** | 10,210 | 0/12 |
| `forced`: the harness delegates the question for it | 12/12 | **2,435** | 1.0 | 12/12 | 8,105 | 0/12 |

  With the rule in the prompt it delegated **0 of 12** times: `grep` found each fact in two or three calls, so it never needed to. When the harness made the delegation, the answers were as right and the parent's conversation ended about 30% smaller. The benefit is real; this model only gets it when asked ("use the explore agent to ...") or when the question needs more reading than a grep.
- A sub-agent is a model call loop: it costs time (a small local model takes tens of seconds per delegation) and tokens, shown in its footer.
- The sub-agent's report is only as good as its task text; a main agent that sends "check the thing" gets a report on nothing. The tool's description says so.
- Every definition adds to the `delegate` tool's description, which is paid on every request: about 140 tokens with two agents (measured with the other tools in Lesson 50).
