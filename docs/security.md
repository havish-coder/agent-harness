# Security model

> This page grows with each release. The full threat model arrives with v0.5.

## What we protect
- **Your files** outside the workspace: they must not be read, changed or deleted.
- **Your secrets**: API keys, tokens and credentials must never reach the model or logs.
- **Your machine**: the agent must not run commands you didn't approve.

## Who might attack
- **The model itself**, by mistake: small models misread instructions and pick wrong paths.
  (A real example during development: asked to list a folder, a model listed `/`, the root of
  the drive.)
- **Content the agent reads**: a file or web page can contain text written to trick the model
  into doing something else (*prompt injection*).

## The shell tool (v0.2)
`run_shell` runs any command you approve **with your full user rights and environment
variables** (which can include API keys). Nothing is sandboxed yet. Read each command before
approving it, and don't use `--yes` outside a throwaway folder.

## Defenses by release
| Defense | Status |
|---|---|
| Tools bound to a workspace folder | v0.1 (paths not yet confined) |
| Approval before any tool that changes something | v0.2 |
| Path jail: paths confined to the workspace | v0.5 |
| Permission modes and allow/deny rules | v0.5 |
| Shell command analysis and environment scrubbing | v0.5 |
| Prompt-injection markers on untrusted content | v0.5 |
| Network guard against requests to private addresses | v0.5 |
| Audit log and secret redaction | v0.5 |
