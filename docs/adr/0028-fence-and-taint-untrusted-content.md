# 0028. Fence untrusted content, and stop blanket approvals once it has been read

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
A language model reads instructions and data through the same channel, so text in a file, a command's
output or a web page can steer it (threat T9). We measured this with `scripts/injection_lab.py`
(Lesson 27): with approvals off (`--mode bypass`), `qwen3:4b-instruct` asked for the injected action in
5 of 9 runs and the harness would have run it unasked in all 5. The model can't be made immune, so the
design question is what the *harness* can do deterministically, and what it can do to make the
model less likely to obey.

The cases differ in who wrote the content. A README in the user's own project was written by the user. The
README of a repository they just cloned was written by its author. A web page was written by anyone.

## Options
1. **Do nothing; rely on approval prompts.** Users with approvals on are protected; users who turned
   them off (modes, rules) are not, and those are the users the lab measured.
2. **Ask for everything after reading anything.** Safe and unusable: the agent reads files all the
   time, so `accept-edits` and rules would never apply.
3. **Mark untrusted content in the prompt** (fencing) and say it is data. Cheap, probabilistic.
4. **Track untrusted content and make broad approvals narrower afterwards** (taint). Deterministic,
   needs a notion of what is untrusted.
5. **Quarantine**: let a model without tools read untrusted content and pass only a summary
   on (a dual-model design). Strongest, costs a model call and detail; a candidate for later.

## Decision
Options 3 and 4, with a per-folder notion of trust (`harness/security/taint.py`, `trust.py`):

- **Fencing.** Results of tools that return outside text (`content_kind`: `file` for `read_file` and
  `grep`, `command` for `run_shell`, `web` for `web_fetch`) are wrapped in
  `<untrusted source="...">...</untrusted>` and the system prompt says text inside is data. A literal
  closing tag inside the content is defused so a file can't end its own fence. Errors and refusals are
  the harness's own words and are not fenced. The user sees the raw result; only the model sees the fence.
  `fence_untrusted` (default on) can be turned off, not from project settings.
- **Taint.** The permission object keeps the list of sources read. Web (and, later, MCP) content always
  counts; file text and command output count only in a folder the user hasn't trusted. When the list
  is non-empty, **broad approvals are not honored**: `bypass`, `accept-edits` and allow rules for a whole
  tool ask instead. Pattern rules and exact "always" answers still run, deny rules and protected paths are
  unchanged, and the question says why. "Always for this whole tool" isn't offered while tainted.
- **Trust.** `/trust` records a folder (and those below it) in the *user's* settings folder; a project
  can't declare itself trusted. `/taint` shows what was read and `/taint clear` is the user's
  explicit "carry on"; `/reset` clears it. A startup notice appears only when a broad approval meets an
  untrusted folder.
- **Ordering.** A call counts as influenced by everything read earlier in the conversation, including
  reads made in the same reply (they run in an earlier batch).

## Consequences
- The setting the lab measured (approvals off, hostile repository) no longer runs an injected action
  unasked: the question is asked (and a person who reads it can say no). The model can still be persuaded;
  what changes is what its persuasion can do without a human.
- Users in their own projects `/trust` once and notice nothing; `default`-mode users notice nothing at all.
- The trust boundary is a user decision about a folder, not an analysis of content: a hostile file in a
  trusted folder isn't noticed. Text attached with `@` is the user's own and isn't fenced or counted.
- Fencing's effect depends on the model following the system prompt; it is measured, not assumed
  (see the lesson), and it adds a few tokens per tool result.
- New tools declare `content_kind` or their output is neither fenced nor counted: a deliberate, reviewable
  place to get it wrong, with a test per tool.
- Not done: quarantine (option 5), nonce-marked fences, fencing text the user attached with `@`.
