# CLI reference

```text
harness [--model MODEL] [--workspace PATH] [--max-steps N] [--yes] [--no-stream] [--think]
```

| Flag | Default | Description |
|---|---|---|
| `--model` | `qwen3:4b-instruct` | Ollama model name. Must support tool calling. |
| `--workspace` | `workspace` | Folder the agent works in. Must exist. |
| `--max-steps` | `20` | Maximum model calls per request before the agent stops. |
| `--yes` | off | Approve every tool call without asking. Only for throwaway folders. |
| `--no-stream` | off | Wait for each complete reply instead of showing text as it is generated. |
| `--think` | off | For thinking models (e.g. `qwen3:4b`): ask for reasoning in a separate field and show it dimmed. |

Exit: `/bye`, Ctrl+D, or Ctrl+C at the prompt.
