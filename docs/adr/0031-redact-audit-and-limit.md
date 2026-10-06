# 0031. Redact secrets by shape, keep a hash-chained audit log, and limit a session

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Three threats from the [threat model](../security.md) remained after the earlier defenses:

- **T14, secrets in transcripts.** `read_file(".env")` hands the model the key; with a cloud provider it is then in
  someone else's logs, and in any chat the user exports or shares. Lesson 30 removed secrets from the *environment*
  of commands; files and command output were untouched.
- **Accountability.** After a long unattended run, the user needs to know what was decided, asked, run and refused.
  The event stream is on screen and gone.
- **T13, runaway use.** `max_steps` bounds one request. Nothing bounded a session: a loop, an injection that keeps
  the agent busy, or an honest long task on a paid model.

## Options
**Redaction:** (1) a list of exact secrets (the user's environment values): misses every secret not in the
environment, e.g. in a file; (2) a model asked "is this a secret?": slow, leaks the secret to the model it was
meant to protect; (3) patterns for known token shapes and for secret-looking names with values; (4) entropy
detection: finds unknown shapes, but flags hashes, ids and base64 constantly.

**Audit:** (1) plain text log in the project: the model can read and edit it; (2) a log in the user's folder; (3)
the same, with each line hashing the one before; (4) an external service or signed log: the only truly
tamper-proof form, out of scope.

**Limits:** a single counter (steps); several independent limits with sensible defaults; limits chosen by the model.

## Decision
- **Redaction (option 3)** in `harness/security/redact.py`: provider key formats, GitHub, AWS, Slack, Stripe, JWT,
  bearer tokens, URL passwords, private key blocks, and `NAME=value` where `secret_name(NAME)` (ADR 0027) with
  a value of at least 8 characters that isn't a reference (`$X`, `os.environ[...]`). Applied to every tool result before
  the model, the screen or the log sees it, and to exported chats. Placeholders say what was hidden
  (`[REDACTED: api key]`). `secret_name` was tightened so `MONKEY` isn't a secret. Setting `redact_secrets`.
- **Audit (options 2 and 3)** in `harness/audit.py`: JSON lines in `~/.harness/audit/YYYY-MM.jsonl`, outside every
  project and never written by a tool. Values are redacted and truncated; results record size and failure, never
  text. Each line carries the first 16 hex digits of the SHA-256 of the previous line; `/audit verify` finds the
  first break. The log is written best-effort: a failure is reported once and never stops the agent. Rotation at 10 MB.
- **Limits** in `harness/limits.py`: tool calls (500), cost ($5, only for models with a known price), tokens and
  minutes (off by default), per chat. Checked before each model call by the session's plain code; every call the
  model *asks for* counts, run or refused. The message names the limit and how to change it. Setting `limits` merges
  across layers.
- **Not from projects:** `audit_log`, `redact_secrets` and `limits` are refused in project settings (each would
  let a repository switch off a protection or raise a ceiling).

## Consequences
- The T14 attack tests pass; a `.env`, a command's output and an exported chat no longer carry the key.
- **False positives and negatives are the price of shape matching.** A fixture key in a test file is hidden (and the
  model can't edit that line); a secret with no shape isn't. Both are documented; the setting is there for people
  who accept the trade.
- The audit log shows tampering but can't prevent it; the hash chain is only as strong as the place the head is kept.
- A $5 default cost limit can stop a legitimate long task on a paid model. The message says how to raise it; a silent
  runaway bill was judged the worse failure.
- Entries are one `write` each (`flush`, not `fsync`): a crash can lose the last few lines. Deliberate: an fsync
  per event would slow every tool call.
- Not done: signing, remote shipping of the log, entropy-based detection, per-tool limits, limits by project.
