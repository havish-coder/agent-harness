# 0047. Skills are loaded on demand, started by name, and are text only

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
Instructions the agent should follow only sometimes (a commit format, a release routine) have three places to live: always in the prompt (`HARNESS.md`, Lesson 41), nowhere (the user retypes them), or **in a file the agent loads when the task needs it**. The first costs tokens on every request, which an 8K window can't spare.
The second makes the agent depend on the user remembering. The third (progressive disclosure) costs a line per skill and the text only when used, but it asks a small model to decide *when*.

Measured (`scripts/skills_lab.py`, `qwen3:4b-instruct`, three diffs, 4 runs each, a strict commit-message format):

| variant | where the rules were | follows the format | called `use_skill` | system prompt (tokens) | tokens used per run |
|---|---|---|---|---|---|
| `none` | nowhere | 0/12 | (no skill) | 298 | 2,148 |
| `memory` | in `HARNESS.md`, so in every prompt | 0/12 | (no skill) | 451 | 2,855 |
| `skill` | one line in the prompt; the text when loaded | 0/12 | **0/12** | 336 | 2,300 |
| `command` | `/commit-message ...`: the user starts it, the text is in the request | **2/12** | 2/12 | 336 | 4,818 |

The format has five rules (a type from a list, at most 50 characters, a blank line, two or three "- " bullets, a last line `Refs: none`) and a message either follows all of them or doesn't.

## Options
1. **Everything in the memory file**: simple; always there; always paid for.
2. **A skill the model must choose to load** (`use_skill`), described by one line in the prompt.
3. **Option 2, and the same text as a slash command** the user can start: the choice made by the user when the model won't make it.
4. **Skills that can grant permissions** (an `allowed-tools` header, as some agents have): convenient, and an escalation: a file that approves a command.

## Decision
Options 2 and 3 (`harness/skills.py`); not 4.

- **A skill is a folder with `SKILL.md`** (header: `description`, optionally `name` and `user-only`), plus any files beside it. Yours are `~/.harness/skills/`; a project's are `.harness/skills/`, **read only in a folder the user trusts** (it is instructions the agent follows, the standing of `HARNESS.md`; a cloned repository must not write them), and never replace one of yours.
- **The prompt carries one line per skill**, at most about 600 tokens, with the count of those left out; the tool `use_skill(name, file)` returns the text (cut at 12,000 characters) or one of the skill's files. **A bundled file can't leave its folder**: the path is resolved and must stay inside (no `..`, absolute paths or links out), text only, 12,000 characters.
  The tool exists only while there is a skill the agent may load (`Tool.enabled`), so a project with no skills pays nothing.
- **Also a slash command**: `/name words` expands to "Follow this skill" and the text, with the user's words in place of `$ARGUMENTS`, so the model doesn't have to decide. It never replaces a built-in command. `user-only: true` keeps a skill out of the prompt and the tool, and leaves the command.
- **Text, not permission**: no header field allows a tool, sets a mode or approves a command; unknown fields are ignored. What the agent does after loading a skill is decided by the permission rules like anything else.
- **Not fenced**: a skill from a place the user trusts is the user's own instruction, so its text reaches the model as the result of `use_skill` without the untrusted-content fence.

## Consequences
- A project with ten skills costs ten lines of prompt, not ten documents. Measured, though: a small model **never loaded a skill by itself** (0 of 12), so the line is only worth it for skills you start by name or for larger models; and with this strict format even the text in every prompt (153 tokens more per request) gave 0 of 12. Started by the user as a command it was the only placement that ever worked (2 of 12). Where instructions live matters less than whether the model can follow them, and a skill that is never loaded costs one line, not a document.
- A skill's quality is its description: a vague one is never loaded. `/skills` shows what the model is told.
- Skills run on the model's judgment as to when to load them; the command route is the reliable one. A later lesson's evals will measure how often a given model loads the right skill.
- A trusted folder's skill is as powerful as its author's instructions: `/trust` means that. The permission rules still decide each action.
