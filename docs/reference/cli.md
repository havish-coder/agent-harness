# CLI reference

```text
harness [--model MODEL] [--workspace PATH] [--max-steps N]
```

| Flag | Default | Description |
|---|---|---|
| `--model` | `qwen3:4b-instruct` | Ollama model name. Must support tool calling. |
| `--workspace` | `workspace` | Folder the agent works in. Must exist. |
| `--max-steps` | `10` | Maximum model calls per request before the agent stops. |

Exit: `/bye`, Ctrl+D, or Ctrl+C at the prompt.
