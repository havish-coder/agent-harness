# 0054. The page opens other chats with slash commands, and other projects and models by rebuilding the session; it never takes a key, nor a folder you haven't used

- **Status:** Accepted
- **Date:** 2026-10-08

## Context
A web UI that can only drive the session it started with is a demo. People want to go back to an earlier chat, start a new one, open
another project, and try another model, from the page. The terminal already has most of it: `/chats`, `/resume`, `/reset`, `/rename`,
`/model` (same provider), `/style`, `/progress`. Two things it doesn't have mid-session: **another project** (the session's workspace,
jail, settings, memory, journal, hooks and MCP servers are all built from one folder, ADR 0050's reason for a start-up flag) and
**another provider** (the provider, its key and the window size are built at start).

Two things the page must never become: a way to point the agent at **any folder** (a bug, or a script in a page that got the key, could
then reach your home folder), and a place where **API keys** are typed (they would pass through a browser, its autofill and its history;
keys come from environment variables only, ADR 0017).

## Options
1. **New endpoints for each chat action** (`/api/chats/resume` ...), duplicating the commands.
2. **The page sends the slash commands** the terminal uses, through `POST /api/send`.
3. **Switch projects and models inside the running session**, changing its parts one by one.
4. **Build a new session** for the project or model, the way `harness --web` builds the first one, and close the old one.

## Decision
Options 2 and 4 (`harness/web/server.py`: `build_session`, `WebApp.replace`, `open_project`, `connect`, `chats_json`, `journal_json`,
`settings_json`; the page's drawers and Journal tab).

- **Chats**: the page sends `/reset`, `/resume ID`, `/rename TITLE`; the journal's buttons send `/progress start|update|stop`; the style
  menu sends `/style NAME`. One code path for both interfaces. When a request leaves a different session, a different message list, or a
  shorter one (`/reset`, `/resume`, `/rewind`, `/compact`), the server publishes `conversation` and every page draws the conversation
  again from `/api/state`.
- **Projects**: `POST /api/project {path}` accepts only a path from the list of projects used before (`ChatStore.projects`, written when a
  chat is saved). Anything else is refused; a new project is opened from the command line (`harness --web --workspace FOLDER`).
- **Models**: `POST /api/connect {provider, model, base_url}`: a known provider, short text, an `http(s)` address. The key is read from
  the provider's environment variable when the session is built; the settings show *whether* it is set (`OPENAI_API_KEY ✓`), never
  its value. The chat carries on: the new session resumes the saved chat.
- **Rebuilding**: `build_session` is what the command line does at start (`.env`, settings with the command line's flags kept, the
  workspace and its extra folders, commands, styles, the session with the page's approver, the banner). The new session is built
  **first**; the old one is closed only if that worked, so a missing key or a bad setting leaves you where you were, with the reason. Both
  run on the worker thread like a request (busy, one at a time).
- **Settings**: shown read-only (where each value came from), with the files to edit. Ollama's model list comes from its `/api/tags`.

## Consequences
- Measured: building a session for the sample workspace takes about 245 ms (400 ms the first time); the page redraws a resumed chat in
  about 45 ms.
- Closing the old session does what closing always does: the journal is updated if things changed, background commands and MCP servers
  stop. The settings say so before you connect.
- A worktree (`--worktree`) stays the command line's; the page doesn't create one.
- Not done (YAGNI): editing settings files from the page, adding a new project from the page, listing an OpenAI-compatible provider's
  models (it needs the key for a request the page doesn't otherwise make).
