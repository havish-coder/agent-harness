# CLI reference

```text
harness [--model MODEL] [--workspace PATH] [--max-steps N] [--yes]
```

| Flag | Default | Description |
|---|---|---|
| `--model` | `qwen3:4b-instruct` | Ollama model name. Must support tool calling. |
| `--workspace` | `workspace` | Folder the agent works in. Must exist. |
| `--max-steps` | `10` | Maximum model calls per request before the agent stops. |
| `--yes` | off | Approve every tool call without asking. Only for throwaway folders. |

Exit: `/bye`, Ctrl+D, or Ctrl+C at the prompt.
