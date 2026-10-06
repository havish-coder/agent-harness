# CLI reference

```text
harness [--provider NAME] [--model MODEL] [--base-url URL] [--fallback-model MODEL] [--workspace PATH] [--max-steps N] [--yes] [--no-stream] [--think] [--plain] [--show-config]
```

| Flag | Default | Description |
|---|---|---|
| `--provider` | `ollama` | Where the model runs: `ollama`, `anthropic`, `ollama-openai`, `lmstudio`, `openai`, `groq`, `openrouter`, `gemini`. See [models](../user-guide/models.md). |
| `--model` | `qwen3:4b-instruct` for Ollama | Model name. Must support tool calling. Required for cloud providers. |
| `--base-url` | the provider's | Another server address, e.g. any OpenAI-compatible server. |
| `--fallback-model` | none | A second model on the same provider, used when the main one keeps failing with temporary errors. |
| `--workspace` | `workspace` | Folder the agent works in. Must exist. |
| `--max-steps` | `20` | Maximum model calls per request before the agent stops. |
| `--yes` | off | Approve every tool call without asking. Only for throwaway folders. |
| `--no-stream` | off | Wait for each complete reply instead of showing text as it is generated. |
| `--plain` | off | Plain text: no colours, Markdown rendering or spinner. Automatic when output isn't a terminal, or when `NO_COLOR` is set. |
| `--show-config` | | Print the effective settings and which layer each came from, then exit. |
| `--think` | off | For thinking models (e.g. `qwen3:4b`): ask for reasoning in a separate field and show it dimmed. |

Flags override settings files and `HARNESS_*` environment variables; see
[configuration](configuration.md).

Exit: `/bye`, Ctrl+D, or Ctrl+C at the prompt.
