# Web API reference

What the page and `harness --web` say to each other ([ADR 0051](../adr/0051-a-standard-library-web-server-with-server-sent-events.md)).
Everything is JSON over HTTP on `127.0.0.1`; every request needs the key (see [who can open it](../user-guide/web-ui.md#who-can-open-it)).

## Endpoints
| Method and path | Body | Answer |
|---|---|---|
| `GET /?key=KEY` | | `303` to `/`, with the cookie `harness_key_PORT` (`HttpOnly; SameSite=Strict`) |
| `GET /` | | the page |
| `GET /static/NAME` | | the page's script and style (only the files that ship with it) |
| `GET /api/state` | | `{"status": {...}, "messages": [event, ...], "last_event": N, "todos": [...], "tasks": [...], "question": {...} or null}` |
| `GET /events?after=N` | | the event stream from event `N + 1` on (see below) |
| `POST /api/send` | `{"text": "..."}` | `{"ok": true}`, or `409` while a request runs, `400` for no text |
| `POST /api/stop` | `{}` | `{"stopping": true}`, or `false` when nothing runs |
| `POST /api/answer` | `{"id": "q3", "answer": ...}` | answer the waiting question: `"yes"`, `"no"` or `"always"` (if offered) for an approval, an option's key (or `""`) for a choice, text (at most 4,000 characters) for text. `{"ok": true}`, `400` for an answer it can't be, `409` when that question isn't waiting (answered already, or stopped) |
| `GET /api/files?path=P` | | `{"path", "entries": [{"name", "path", "dir"}]}`: folder `P` of the workspace (`""` for its root), folders first, without the folders the tools skip (`.git`, `node_modules` ...); `403` outside the workspace, `404` if it isn't a folder |
| `GET /api/file?path=P` | | `{"path", "text", "truncated"}` (the first 200 KB, secrets hidden), or `{"path", "binary": true}`; `403` outside the workspace, `404` if it isn't a file |

Refusals: `403` when the `Host` header isn't `127.0.0.1:PORT` or `localhost:PORT`; `401` without the key; `400` for a body
that isn't a JSON object (or is over 1 MB).

`status` is what the status line shows: `provider`, `model`, `context_tokens`, `context_window`, `cost` (`null` when the
price is unknown), `style`, `mode`, `tasks_running`, `workspace`, `turns`, `busy`.

`todos` is the todo list (`[{content, status}]`), `tasks` the background commands (`[{id, command, text, running}]`), `question` the
question the agent is waiting on (the `question` event below), if any.

`messages` is the conversation so far, as the same events the stream carries (`user`, `answer`, `tool_call`,
`tool_result`), preceded by what the server said at start-up (`info`, `warn`). Draw them, then stream from `last_event`.

## The event stream
`GET /events` is [Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html): one block per event,

```text
id: 42
data: {"type": "tool_call", "id": "c1", "name": "read_file", "args": {"path": "notes.txt"}}

```

and a `: ping` comment every 15 s when nothing happens. A client that reconnects sends `Last-Event-ID: 42` (the browser's
`EventSource` does it by itself) and gets everything after 42 that the server still has (the newest 5,000 events).

| `type` | Fields | When |
|---|---|---|
| `user` | `text` | a request was accepted (shown in every open page) |
| `busy` | `busy`, `status` (when it ends) | a request started or ended |
| `context` | `tokens`, `window`, `level` | before each model call ([context](../user-guide/context.md)) |
| `model_call` | | the model is being asked |
| `text_delta` | `text` | a piece of the answer |
| `thinking_delta` | `text` | a piece of a thinking model's reasoning |
| `model_reply` | `input_tokens`, `output_tokens` | a reply is complete |
| `tool_call` | `id`, `name`, `args` | the model asked for a call |
| `tool_result` | `id`, `name`, `text` (first 4,000 characters), `chars`, `error` | after every call, run or not |
| `tool_denied`, `tool_refused` | `id`, `reason` | you said no; the permissions refused it |
| `answer` | `text`, `markdown` (math converted to Unicode: draw this one) | the final answer of a request |
| `usage` | `text` | tokens and cost of the request |
| `todos` | `items`: `[{content, status}]` | the todo list changed |
| `task` | `id`, `command`, `text` | a background command ended |
| `subagent` | `name`, `what` (`start`, `tool_call`, `end`), `info` | a sub-agent started, called a tool, finished |
| `question` | `id`, `kind`; for `approval`: `call_id`, `tool`, `args`, `preview` (the diff), `reason`, `notes`, `destructive`, `always` (what "always" would allow, or `null`); for `choice`: `question`, `options` (`{key: label}`); for `text`: `question` | the agent waits for an answer (`POST /api/answer`) |
| `answered` | `id`, `answer` (`true`/`false` for text: whether something was typed) | a question was answered, or Stop answered it |
| `plan` | `text`, `markdown` | plan mode proposes a plan; a `choice` question follows |
| `rolled_back` | | a request that failed or was stopped was removed from the conversation |
| `note` | `text` | the harness did something worth a line: cleared old results, summarised, a limit, hid a secret |
| `info`, `warn`, `error` | `text` | messages, as the terminal prints them |

The `events.md` [reference](events.md) describes the agent events these come from.
