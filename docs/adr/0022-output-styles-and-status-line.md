# 0022. Output styles as system-prompt additions; status line computed per prompt

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Users want the agent to write differently in different situations: briefly when they're busy,
with explanations when they're learning, with typeset math for technical work. They also need to
see the state of a session at a glance, especially how full the context window is, because a full
window silently loses the beginning of the conversation on Ollama.

## Options
1. **Ask in each message** ("be brief"): works for one turn; easy to forget.
2. **Output styles**: named instruction blocks appended to the system prompt, switchable mid-session.
3. **A status line redrawn continuously** with fresh data (including a user command) vs **computed
   once per prompt**.

## Decision
Output styles (option 2): built-in and Markdown-defined, applied with `apply_style()`, switched with
`/style`, which rewrites the system message of the running conversation. The status line is
computed once before each prompt, from the last model call's token counts. A user-supplied
`status_line` command gets the session state as JSON with a 2-second timeout, and may not come
from project settings because it runs a program.

## Consequences
- Switching style changes the first message, so the provider's prompt cache can't be reused for the
  next call; the guide recommends choosing a style at the start.
- The status line can be a few seconds stale while typing; running a program on every keystroke
  would be too slow.
- A project can ship styles (useful for teams) but can't replace the built-in ones.
