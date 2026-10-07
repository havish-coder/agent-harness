# Secrets, the audit log and limits

Three protections that work quietly in the background, and what each one does and doesn't do.

## Secrets are hidden from the model
A secret in a file is read like any other text, and what the agent reads goes to the model (and, with a cloud
provider, to someone else's server). Before a tool result reaches the model, the screen or the audit log,
Agent Harness replaces anything shaped like a secret:

```text
you> What does .env define?
  read_file(path='.env')   2 lines
ANTHROPIC_API_KEY=[REDACTED: api key]
DEBUG=1
```

It recognises, by their **shape**: OpenAI/Anthropic/Groq/Google API keys, GitHub tokens, AWS access key ids,
Slack and Stripe keys, JSON web tokens, `Authorization: Bearer ...`, passwords in URLs
(`postgres://user:pw@host`), private key blocks, and `NAME=value` pairs where the name says secret
(`DB_PASSWORD=...`, `"client_secret": "..."`). Values that merely *point* at a secret (`$KEY`,
`os.environ["KEY"]`, `<your key>`) and short values (`TOKEN=1`) are left alone.

It's a filter on shapes, so it has limits:
- A secret with no recognisable shape (a plain word used as a password, in a file with no hint) isn't caught.
- Something that only *looks* like a secret is hidden: a fixture key in a test file. The model can't edit
  a line it can't see, so an `edit_file` on a redacted line fails, and you make that edit yourself.
- It applies to what **tools return**. What *you* type or paste into the prompt isn't changed.

Exported chats (`/export`) go through the same filter. `"redact_secrets": false` in your user or local settings
turns it off (a project can't).

## The audit log
Every chat leaves a record of what the agent did, in your own settings folder, outside any project:
`~/.harness/audit/2026-10.jsonl` (one file a month; rotated at 10 MB). One JSON object per line:

```text
/audit                       the last 15 entries and the file's location
/audit 40                    the last 40
/audit verify                is the file intact?
```
```text
23:20:58 decision   tool='read_file' subject='.env' action='allow' reason='reads only'
23:20:58 redacted   tool='read_file' kinds=['api key']
23:20:58 model      model='qwen3:4b-instruct' input_tokens=1753 output_tokens=40 stop='tool_calls'
```

It records: the session start (folder, model, mode, whether the folder is trusted, the tools), every permission
decision and the reason, your answers to questions (`approved`, `user_denied`), results (size and whether they
failed, never the text), hooks, secrets that were hidden, model calls with token counts, mode and trust changes,
limits reached, old tool results cleared to make room (which tools, how many tokens), and the end of the chat with totals. Values are redacted and cut to 500 characters.

**Tamper-evident, not tamper-proof.** Each line carries a hash of the line before it, so `/audit verify` finds a
line that was changed, removed or reordered. Someone with write access to the file can rewrite all of it; if that
matters, copy the file somewhere they can't reach.

The model can't alter it: the file is outside the workspace, written by the harness and never by a tool. If it can't
be written (disk full, no permission) the app says so once and keeps working. `"audit_log": false` turns it off
(a project can't).

## Limits
A session that loops, is steered by a hidden instruction, or just works for hours can cost real money. Every
chat has limits, checked before each step, and when one is reached the agent stops and says which:

```text
(stopped: 501 tool calls (limit 500). /limits shows the limits; raise one in your settings, or /reset to start a new chat)
```

| Limit | Default | Counts |
|---|---|---|
| `tool_calls` | 500 | every call the model asks for, run or refused |
| `cost` | $5.00 | money spent in this chat, for models with a known price (see `/cost`); a model with no price has no cost limit |
| `tokens` | none | input and output tokens, summed over every model call |
| `minutes` | none | time since the chat started |

```json
{ "limits": { "cost": 20, "tool_calls": 2000, "minutes": 90 } }
```

Layers change only what they name; `null` means no limit; a **project can't set limits** (it could raise them).
`/limits` shows what the chat has used against each limit, and `/reset` starts counting again. The per-request
`max_steps` limit still applies on top.
