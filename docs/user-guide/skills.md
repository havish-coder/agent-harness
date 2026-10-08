# Skills

A project collects know-how that matters only sometimes: how a commit message should look here, how to cut a release, how to review a migration. Put it all in the system prompt and every request pays for all of it, which a small window can't afford.
Put none of it there and the agent doesn't know it exists. A **skill** is the middle way: the prompt carries **one line** per skill, and the full text is loaded **when it is needed**.

```text
your folder/skills/commit-message/SKILL.md
project/.harness/skills/release/SKILL.md          (read only in a folder you trust)
```

```markdown
---
description: Write a commit message in this project's format
---
First line: `type(scope): summary`, type one of feat, fix, docs, refactor, test, at most 50 characters ...
```

- The **description** (one line, 160 characters) is what the agent sees in its prompt: *"- commit-message: Write a commit message in this project's format"*. Make it say **when** to use the skill.
- The **text** is what `use_skill("commit-message")` returns to the agent. As long as it needs to be (cut at 12,000 characters).
- **Other files** in the skill's folder (an example, a checklist) are read with `use_skill("commit-message", file="example.md")`. A skill's files can't be left: no `..`, no absolute paths, no links out, text files only.
- The prompt lists at most about 600 tokens of skills; the rest are counted ("5 more: /skills lists them").

## Two ways in
- **The agent loads it** when the task matches the description: `use_skill`. A small model does this less often than you'd like: see what it measured.
- **You start it**: every skill is also a **slash command**, `/commit-message the change to cart.py`. It loads the skill and sends your words with it: nothing is left for the agent to decide. A skill never replaces a built-in command.

Add `user-only: true` to the header to keep a skill out of the agent's list (a deploy, say): only `/deploy` starts it.

`/skills` lists them (where each is from, how many files it has); `/skills reload` reads them again (also done when you `/trust` a folder).

## It is instructions, not permission
A skill is **text**. Nothing in its header can allow a tool, change the permission mode or approve a command; what the agent does after loading one is decided by the [permission rules](permissions.md) as always. (A header line like `allowed-tools:` is simply ignored.)

It does have the standing of [HARNESS.md](memory.md): the agent follows it. So **yours are always read; a project's only in a folder you trust**, because a cloned repository must not get to write instructions the agent follows. In an untrusted folder you get a note
("2 skill(s) were not read") and `/trust` loads them. A project's skill can't replace one of yours with the same name.

## What it measured
A commit message for a small diff in a strict five-rule format (`scripts/skills_lab.py`, `qwen3:4b-instruct`, three diffs, four runs each):

| variant | where the rules were | follows the format | called `use_skill` | system prompt (tokens) | tokens used per run |
|---|---|---|---|---|---|
| `none` | nowhere | 0/12 | (no skill) | 298 | 2,148 |
| `memory` | in `HARNESS.md`, so in every prompt | 0/12 | (no skill) | 451 | 2,855 |
| `skill` | one line in the prompt; the text when loaded | 0/12 | **0/12** | 336 | 2,300 |
| `command` | `/commit-message ...`: the user starts it, the text is in the request | **2/12** | 2/12 | 336 | 4,818 |

This small model **never loaded the skill by itself** (0 of 12): the one-line listing wasn't enough. Started by name (`/commit-message ...`) it was the only way it ever followed the format (2 of 12); the same text in `HARNESS.md`, paid for in every request, gave 0 of 12. With a small model, **start skills yourself with their slash command**, and keep their rules few.

## Setting
`"skills": false` turns skills off (no list in the prompt, no tool, no commands). A project may set it.
