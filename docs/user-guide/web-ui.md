# The web UI

The same agent, in your browser: the same settings, tools, permissions, chats and slash commands as the terminal app,
with the answer streamed into a page.

## Starting it
```bash
harness --web
```

The server starts on port 8765, prints an address and opens it in your browser:

```text
Agent harness in your browser: http://127.0.0.1:8765/?key=1Qe8...
(only this computer can open it; Ctrl+C here stops the server)
```

Every other flag works as in the terminal: `harness --web --workspace ~/code/shop --model qwen3:8b`, `--mode plan`,
`--worktree fix-cart`, `--context-window 16384`.

| Flag | |
|---|---|
| `--web` | serve on port 8765 |
| `--web 9000` | another port; `--web 0` picks a free one |
| `--no-browser` | print the address, don't open a browser |

Stop the server with **Ctrl+C** in its terminal. The session ends as it does in the terminal: the progress journal is
updated if there is one, and background commands and MCP servers are stopped.

## Using it
- Type a request and press **Enter** (Shift+Enter for a new line). Slash commands work as in the terminal: `/cost`,
  `/context`, `/mode plan`, `/model qwen3:8b`, `/undo` ... (`/bye` doesn't: close the tab).
- The answer appears as it is written, with each tool call and the start of its result.
- **Stop** ends the request, as Esc does in the terminal: what the request added to the conversation is removed. A long
  command that is already running finishes first.
- One request at a time. You can open the page in several tabs: they all show the same session, and any of them can send.
- Reloading the page, or a dropped connection, loses nothing: the page loads the conversation and carries on from the last
  event it saw.

### Approvals
In this version the page can't answer approval questions yet. A call that would ask (an edit, a command that changes
something) is refused, and the model is told it can't run here. Calls your [rules](permissions.md#rules) or
[mode](permissions.md) allow still run. For changes that need your yes, use the terminal app for now.

## Who can open it
- The server listens on **127.0.0.1**: other computers on your network can't reach it.
- Every request needs the **key** in the printed address. The first visit swaps it for a cookie and removes it from the
  address bar, so it isn't left in your history or shared in a screenshot. A new server makes a new key.
- Requests that name another site in their `Host` header are refused. This stops a web page you visit from pointing a
  domain at 127.0.0.1 and talking to the server through it (DNS rebinding).

Anyone with the address (key included) can drive the agent with your permissions until the server stops: don't paste it
anywhere.

## Troubleshooting
| You see | Do |
|---|---|
| `error: can't listen on port 8765 ...` | another program (or another harness) uses the port: `--web 0`, or another number |
| *This page needs the key* | open the full address the server printed (it ends with `?key=...`) |
| the status says *reconnecting…* | the server stopped or restarted; start it again and open the new address |
| `wrong Host` | open `127.0.0.1` or `localhost` with the port, not another name |

See also: [the web API](../reference/web-api.md) for what the page and the server say to each other.
