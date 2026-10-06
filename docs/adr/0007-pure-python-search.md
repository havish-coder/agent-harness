# 0007. Implement search in pure Python

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
A coding agent needs to find files by name and text inside files. The fastest tool for this
is ripgrep (`rg`), which respects `.gitignore` and is far quicker than Python on large trees.
It is a separate binary, though: users must install it, or we must ship one per platform.

## Options
1. **Shell out to ripgrep**: fast; an external dependency, different output and regex
   dialect per version, and a second search engine to secure.
2. **Let the model use the shell** (`grep -r`, `findstr`): no new code; commands differ per
   OS, every search needs approval, and output isn't capped.
3. **Pure Python** (`os.walk`, `fnmatch`, `re`): slower on big repositories, but no
   dependency, identical everywhere, read-only, and output shaped for the model.

## Decision
Option 3, with a fixed skip list (`.git`, `.venv`, `node_modules`, caches), binary-file
detection, a 2 MB per-file limit and capped results.

## Consequences
- Searching a large monorepo is slower; the caps keep results useful.
- `.gitignore` rules are not applied yet; only the fixed skip list.
- The regex dialect is Python's, which the tool description states.
- A later ADR may add ripgrep as an optional fast path behind the same tool interface.
