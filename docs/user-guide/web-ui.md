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

## The page
```text
┌ rail ┬ File Explorer ┬ Conversation | File ──┬ Run Graph ──────┬ Agent Control Center ┐
│  ▣   │ data/         │ YOU  …                │   ◉──○ read_file│ Model   qwen3:4b-…   │
│  ✣   │ project/  M   │ ● read_file cart.py   │    \            │ Mode    [default ▾]  │
│  ▭   │ recipes/      │ AGENT  …answer…       │     ○ answer    │ Context ▰▰▰▱ 3.2k/8.2k│
│      │               ├───────────────────────┴─────────────────┤ Agent Log            │
│      │               │ System Status & Terminal Output         │ Task Queue           │
│      │               │ $ python -m pytest …                    │ [ Ask the agent… ➤ ] │
└──────┴───────────────┴─────────────────────────────────────────┴──────────────────────┘
```

- **Conversation**: your requests, the answers (Markdown: tables, code with highlighting, math as Unicode characters), and
  each tool call as a line you can click to see its result. A red dot is a call that failed; an empty one, a call that
  didn't run.
- **File**: click a file in the explorer, or a path in a tool call, to read it here (the first 200 KB; secrets such as API
  keys are hidden, as in the agent's own results).
- **File Explorer**: the workspace, as the agent's tools see it (`.git`, `node_modules` and the like left out). Files the
  agent changed in this session are marked **M**.
- **Run Graph**: what the agent did. Each request is a magenta node, linked to the one before; its tool calls are cyan
  nodes around it, a sub-agent is violet with its own calls, the answer is white. Running calls pulse, failed ones are red,
  calls that didn't run are dashed, and a request you stopped fades. Click a tool node to see its result.
- **System Status & Terminal Output**: the commands the agent ran and what they printed, the context size before each
  model call, and the harness's messages.
- **Agent Control Center**: the model, the permission mode (changing it runs `/mode`), how full the context window is, the
  cost, and what the agent is doing now. **Agent Log**: every step, with the time. **Task Queue**: the agent's todo list
  and its background commands.
- The rail on the left hides or shows the explorer, the graph and the terminal. On a narrow screen the panels stack, with
  the conversation first.

## Using it
- Type a request and press **Enter** (Shift+Enter for a new line). Slash commands work as in the terminal: `/cost`,
  `/context`, `/mode plan`, `/model qwen3:8b`, `/undo` ... (`/bye` doesn't: close the tab).
- **Stop** (■, next to Send while the agent works) ends the request, as Esc does in the terminal: what the request added to
  the conversation is removed. A long command that is already running finishes first.
- One request at a time. You can open the page in several tabs: they all show the same session, and any of them can send.
- Reloading the page, or a dropped connection, loses nothing: the page loads the conversation and carries on from the last
  event it saw. The graph is redrawn from the conversation; only a sub-agent's own steps aren't (the conversation keeps its
  report, not its steps).
- Nothing in an answer runs in the page: HTML the model writes is shown as text, pictures are never loaded (the words
  *[image: ...]* stand in for them), and links open only `http` and `https` addresses, in a new tab. The page loads nothing
  from other sites.

### Approvals and questions
What runs without asking, what asks and what is refused are decided exactly as in the terminal
([permissions](permissions.md)). When a call asks, a card appears in the conversation:

```text
? edit_file wants to run
--- a/project/shop/cart.py
+++ b/project/shop/cart.py
@@ -13,5 +13,5 @@
-        return sum(price for _, price, qty in self.items)
+        return sum(price * qty for _, price, qty in self.items)
[ Yes ]  [ No ]  [ Always allow every edit_file call (this session) ]
```

- An edit shows its **diff** (new lines green, removed lines red); a command shows the **command**; other tools their arguments.
- When the permissions explain themselves, the card says why it asks and lists the risks they found (*deletes files*, *rewrites
  history* ...) in red, as the terminal does. A call that may destroy data says so.
- **Always allow** appears when the permissions can offer a rule: for a command, that exact command; for an edit tool, every call of
  it; for a web page, that site. It lasts until the server stops.
- The agent's own questions (`ask_user`) show their choices as buttons, or a box for a typed answer. Plan mode shows the proposed
  plan and asks *Go ahead with this plan?* The progress journal's offer is a question too.
- While the agent waits, the tab's title starts with ● and the waiting call pulses amber in the graph. The question waits as long
  as it takes; every open tab shows it, and the first answer counts.
- **Stop** while a question waits answers it *no* and stops the request.
- Pressing Enter while the agent works sends nothing: one request at a time. The box shakes and says so.

## Who can open it
- The server listens on **127.0.0.1**: other computers on your network can't reach it.
- Every request needs the **key** in the printed address. The first visit swaps it for a cookie and removes it from the
  address bar, so it isn't left in your history or shared in a screenshot. A new server makes a new key.
- Requests that name another site in their `Host` header are refused. This stops a web page you visit from pointing a
  domain at 127.0.0.1 and talking to the server through it (DNS rebinding).

Anyone with the address (key included) can drive the agent and answer its questions, with your permissions, until the
server stops: don't paste it anywhere.

## Troubleshooting
| You see | Do |
|---|---|
| `error: can't listen on port 8765 ...` | another program (or another harness) uses the port: `--web 0`, or another number |
| *This page needs the key* | open the full address the server printed (it ends with `?key=...`) |
| the status says *reconnecting…* | the server stopped or restarted; start it again and open the new address |
| `wrong Host` | open `127.0.0.1` or `localhost` with the port, not another name |

See also: [the web API](../reference/web-api.md) for what the page and the server say to each other.
