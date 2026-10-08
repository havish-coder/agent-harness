# CLI reference

```text
harness [--provider NAME] [--model MODEL] [--base-url URL] [--fallback-model MODEL] [--workspace PATH] [--max-steps N] [--context-window TOKENS] [--mode MODE] [--yes] [--no-stream] [--think] [--plain] [--show-config] [-c] [-r [CHAT]] [--no-save] [--fresh] [--worktree NAME] [--web [PORT]] [--no-browser]
```

| Flag | Default | Description |
|---|---|---|
| `--provider` | `ollama` | Where the model runs: `ollama`, `anthropic`, `ollama-openai`, `lmstudio`, `openai`, `groq`, `openrouter`, `gemini`. See [models](../user-guide/models.md). |
| `--model` | `qwen3:4b-instruct` for Ollama | Model name. Must support tool calling. Required for cloud providers. |
| `--base-url` | the provider's | Another server address, e.g. any OpenAI-compatible server. |
| `--fallback-model` | none | A second model on the same provider, used when the main one keeps failing with temporary errors. |
| `--workspace` | `workspace` | Folder the agent works in. Must exist. |
| `--max-steps` | `20` | Maximum model calls per request before the agent stops. |
| `--context-window` | `8192` | The model's window in tokens: what the harness plans for, and Ollama's `num_ctx`. At least 4,096. Bigger costs memory and speed ([a bigger window](../user-guide/context.md#a-bigger-window)). |
| `--mode` | `default` | Permission mode: `default`, `accept-edits`, `plan` or `bypass`. See [permissions](../user-guide/permissions.md). |
| `--yes` | off | Same as `--mode bypass`: tool calls run without asking, except deny rules and protected paths. Only for throwaway folders. |
| `--no-stream` | off | Wait for each complete reply instead of showing text as it is generated. |
| `--plain` | off | Plain text: no colours, Markdown rendering or spinner. Automatic when output isn't a terminal, or when `NO_COLOR` is set. |
| `--show-config` | | Print the effective settings and which layer each came from, then exit. |
| `-c`, `--continue` | off | Carry on with the most recent chat in this folder ([chats](../user-guide/chats.md)). |
| `-r`, `--resume [CHAT]` | | Carry on with a saved chat: its number in `/chats`, a word from its title, or the start of its id. With no value, choose from a list. |
| `--fresh` | off | Don't read the project's progress journal this time ([journal](../user-guide/journal.md)). |
| `--no-save` | off | Don't save this conversation (the `save_chats` setting, for one run). |
| `--worktree NAME` | | Work in a git worktree of your own: `<repository>/.harness/worktrees/NAME` on branch `harness/NAME`, made from the commit checked out now, or resumed. Removed when you leave if nothing in it changed; otherwise kept, with the commands to carry on, merge or remove it ([worktrees](../user-guide/worktrees.md)). |
| `--web [PORT]` | | Open the agent in your browser instead of the terminal: a server on `127.0.0.1`, port 8765 unless you give one (`0` picks a free one). Prints the address with its key and opens it ([web UI](../user-guide/web-ui.md)). |
| `--no-browser` | off | With `--web`: print the address, don't open a browser. |
| `--think` | off | For thinking models (e.g. `qwen3:4b`): ask for reasoning in a separate field and show it dimmed. |

Flags override settings files and `HARNESS_*` environment variables; see
[configuration](configuration.md).

Exit: `/bye`, Ctrl+D, or Ctrl+C at the prompt. With `--web`: Ctrl+C in the server's terminal.
