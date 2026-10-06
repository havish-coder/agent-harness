# 0017. Layered JSON settings; secrets only in the environment

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Flags were becoming long (`--provider groq --model ... --fallback-model ...`). Users need
per-machine preferences, settings shared by a project's team, and personal per-project
overrides. Some options are secrets (API keys); some are security-relevant (where prompts are
sent). The project targets Python 3.10, which has no TOML parser in the standard library.

## Options
1. **TOML**: friendly for humans; needs a dependency on 3.10 (ADR 0002 forbids casual ones).
2. **JSON**: in the standard library, unambiguous, machine-editable; no comments.
3. **One file**: simple; can't separate shared from personal settings.
4. **Layers**: defaults < user < project < local < environment < flags.

## Decision
JSON files in layers (option 2 + 4), merged key by key, each value remembering its source.
Unknown keys warn with suggestions; wrong types and invalid JSON are errors. Settings files may
not contain secrets: secret-like key names and key-like values are refused. Keys come from the
environment, optionally loaded from `.env` files that never override existing variables. When
a **project** file sets `provider` or `base_url`, startup shows a warning, because a cloned
repository could otherwise redirect the user's prompts to a server of its choosing.

## Consequences
- No comments in settings files (JSON); the reference documents every key instead.
- `--show-config` makes the merge debuggable.
- New settings must be added to `Settings` and the `TYPES` table, and documented in the reference.
- Lists (e.g. future permission rules) will need a merge rule of their own: concatenate rather
  than replace.
