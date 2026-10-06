# 0021. Slash commands: local code, or Markdown prompt templates

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
The terminal app had three hard-coded commands. Users need more: app actions (switch model, show
settings) and reusable requests to the model. Measurements in this project showed that small
models verify their work only when the request says so; a reusable request that always says so
would capture that knowledge once. Commands can also come with a project, written by whoever
owns the repository.

## Options
1. **Commands as Python plugins**: powerful; running code from a cloned repository is dangerous.
2. **Commands as prompt templates in Markdown files**, with frontmatter for description and
   argument hint, and `$ARGUMENTS`/`$1` placeholders; plus built-in local commands written in
   Python.

## Decision
Option 2. Two kinds: `local` (Python, built in, never reach the model) and `prompt` (text sent to
the model). Prompt commands load from `~/.harness/commands/` and `<workspace>/.harness/commands/`;
later folders override earlier ones, except that a project file can never replace a built-in
command.

## Consequences
- Users write commands without code; teams share them by committing the folder.
- A project command is only text for the model; anything the model then does still needs
  approval. It is still untrusted text (prompt injection, Module 5).
- Running code from commands (for example to gather context first) would need a separate,
  explicitly trusted mechanism.
