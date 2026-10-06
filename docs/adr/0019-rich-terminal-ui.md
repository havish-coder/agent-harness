# 0019. Render the terminal with rich, keep a plain fallback

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
The terminal app printed raw Markdown (`**bold**`, `# headings`) and plain diffs, with no sign
of life while the model was thinking. A coding agent spends most of its time showing model
output and code changes, so readability matters. The output must also stay usable when piped
to a file or another program, where colours and animations are noise.

## Options
1. **Hand-written ANSI codes**: no dependency; Markdown and syntax highlighting are big jobs.
2. **`rich`**: Markdown, syntax highlighting, live-updating regions and spinners, Windows
   support; a well-maintained optional dependency.
3. **A full-screen TUI framework** (Textual, prompt_toolkit's full-screen apps): powerful; takes
   over the terminal and the scrollback.

## Decision
Option 2, as the `tui` extra (allowed for interfaces by ADR 0002). `RichUI` and `PlainUI`
implement the same interface (an event handler plus `answer`, `info`, `warn`, `error`,
`banner`, `usage_line`, `read_input`); `make_ui()` picks rich only when it is installed, stdout
is a terminal and `NO_COLOR` isn't set. Output stays in the normal scrollback.

## Consequences
- Streaming Markdown is re-rendered as it grows (rich `Live`); only one live region (answer or
  spinner) exists at a time.
- Tests render into a recording console; the README's demo image is produced the same way, from
  the replay cassette, so it is reproducible.
- Non-ASCII glyphs (`●`, `└`) need a UTF-8 capable terminal; plain mode avoids them.
