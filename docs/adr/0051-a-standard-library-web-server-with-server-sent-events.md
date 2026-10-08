# 0051. The web interface is a standard-library HTTP server that streams events with Server-Sent Events

- **Status:** Accepted
- **Date:** 2026-10-08

## Context
The terminal app drives a `Session` through two hooks: a ui (a callable for events, plus `info`, `warn`, `answer` ...) and an approver.
A browser interface needs the same session, a way to send it a request, and a way to watch everything it reports while it works:
streamed text, tool calls and results, the todo list, context, costs. Requests are rare (a few per minute); events are many (one per
streamed piece of text, about 10 a second on a 4B local model, a few hundred a second from a fast cloud model).

The plan said FastAPI and uvicorn. Since Lesson 51 the code follows a rule: the standard library before a dependency, and a
dependency only when the standard library can't do the job reasonably.

## Options
1. **FastAPI + uvicorn** (async). Routing, request parsing and streaming responses are built in. But the agent loop is synchronous
   and blocking, so every request would cross from async into a thread anyway. It adds about a dozen packages (pydantic,
   starlette, anyio, h11 ... : 14 with fastapi and uvicorn, as installed here) and a `[web]` extra to install.
2. **`http.server.ThreadingHTTPServer`** (standard library): one thread per connection, a dozen lines of routing.
3. **WebSockets** for both directions. There is no WebSocket server in the standard library; writing the protocol (handshake, framing,
   masking) is real work and real risk.
4. **Server-Sent Events** for server to page, plain `POST`s for page to server. SSE is one long HTTP response of `id:` / `data:` lines;
   the browser's `EventSource` parses it, reconnects by itself, and sends the last id it saw in a `Last-Event-ID` header.

## Decision
Options 2 and 4 (`harness/web/server.py`, started with `harness --web [PORT]`).

- **One session per server**, built exactly as the terminal builds it, with `WebUI` as its ui. A request (`POST /api/send`) runs on a
  worker thread through the same `handle_line` as the terminal, so slash commands behave the same. One request at a time: a second
  gets 409.
- **Every event is numbered** by a hub that keeps the newest 5,000. `GET /events` streams from a number on (`?after=N` the first time,
  `Last-Event-ID` when reconnecting) and sends a comment every 15 s on a quiet stream, which also notices a closed tab. Events go out
  as JSON with a `type` field ([web API](../reference/web-api.md)).
- **A page that opens late** loads `/api/state`: the conversation rebuilt from the agent's messages, as the same JSON events the stream
  carries, plus the number of the last event; then it streams from there. The conversation's source of truth stays `agent.messages`;
  the stream is only what changed.
- **Stop** sets a flag; the next event in the worker thread raises `KeyboardInterrupt`, and the agent's own cancel path rolls the turn
  back, as Esc does in the terminal.
- **Who may connect**: the server binds 127.0.0.1 only; the `Host` header must name it (DNS rebinding); every request needs a random
  key, given once in the address the server prints and swapped at once for an `HttpOnly`, `SameSite=Strict` cookie, named after the
  port because cookies don't separate ports. On Windows the port is bound exclusively: Python's default `SO_REUSEADDR` there lets a
  second server bind the same port (measured), and requests would go to either.
- **No approver yet**: a call that would ask is refused with the ordinary "approval isn't possible in this session" (fail-closed) until
  the page can answer (Lesson 55).
- **No dependencies**: the page's files ship inside the package, and the `[web]` extra is empty (kept so `pip install ".[web]"` still
  works).

## Consequences
- Measured on the development laptop (scripted model, in-process client): an event reaches a page **0.34 ms** after it is published
  (median; p95 0.70 ms), **0.86 ms** with five pages open, and one stream carries about **60,000 events a second**. With
  `qwen3:4b-instruct`, the time to the first word was the same through the page as in the terminal (212-222 ms vs 189-246 ms):
  the model, not the server, sets the pace.
- A thread per open page: fine for one person's browser tabs, not for a public service (which this isn't).
- Stop is noticed at the next event, so a long shell command or a model call without streaming finishes first.
- Not done (YAGNI): HTTPS (the traffic never leaves the machine), several sessions per server (Lesson 56 switches the one session
  between chats), compression, a WebSocket upgrade.
