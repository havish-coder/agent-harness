# 0008. Edit files by exact string replacement, only after reading them

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
The agent must change files. How the model *describes* a change decides how often edits go
wrong. Models are poor at counting lines and at producing well-formed patches, and a file can
change between the model reading it and editing it (the user saves in an editor, a formatter
runs).

## Options
1. **Whole-file rewrites only**: simple; long files cost many output tokens, and models
   silently drop or alter unrelated parts.
2. **Line-number edits** ("replace lines 12-14"): compact; models miscount, and numbers go
   stale after the first edit.
3. **Unified-diff patches**: precise; small models produce malformed hunks.
4. **Exact string replacement** (`old_string` to `new_string`, which must match once): the
   model quotes text it has seen, which it does reliably; ambiguity is detectable.

## Decision
Option 4 for `edit_file`, with option 1 available as `write_file` for new files and full
rewrites. Both require that an existing file was read in this conversation and hasn't changed
since: modification time first, then a SHA-256 of the content (timestamps alone give false
alarms, e.g. from antivirus or sync tools). Errors explain how to fix the call (the most
similar line, the line numbers of every duplicate).

## Consequences
- In live tests `qwen3:4b-instruct` fixed the sample project's bug with `edit_file` in 3 of 3
  runs.
- The model must read before editing: one extra step, but no blind edits.
- `write_file` stays risky for edits: asked to add one test function, the model rewrote the
  whole file in 3 of 3 runs and dropped the existing tests once. The tool descriptions say to
  prefer `edit_file`; running the tests (the shell tool) catches the rest.
