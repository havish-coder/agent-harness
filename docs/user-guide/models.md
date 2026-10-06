# Choosing a model and provider

The agent can run on a model on your own computer (free, private, slower) or on a cloud
service (an account and an API key, faster and stronger models).

```bash
harness                                              # Ollama, qwen3:4b-instruct (the default)
harness --model qwen3:4b --think                     # another Ollama model; show its reasoning
harness --provider anthropic                         # Claude (claude-sonnet-5-5 by default)
harness --provider groq --model llama-3.3-70b-versatile
harness --provider openrouter --model qwen/qwen3-coder
harness --provider lmstudio --model your-loaded-model
```

## Providers
| `--provider` | Runs on | API key variable | Default address |
|---|---|---|---|
| `ollama` (default) | your computer, via Ollama's native API | none | `http://localhost:11434` |
| `anthropic` | Anthropic (Claude models) | `ANTHROPIC_API_KEY` | `https://api.anthropic.com` |
| `ollama-openai` | your computer, via Ollama's OpenAI-compatible API | none | `http://localhost:11434/v1` |
| `lmstudio` | your computer, via LM Studio | none | `http://localhost:1234/v1` |
| `openai` | OpenAI | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| `groq` | Groq | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` |
| `openrouter` | OpenRouter (many models) | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` |
| `gemini` | Google Gemini (compatibility endpoint) | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` |

`ollama` and `anthropic` use their vendors' own APIs. Every other provider uses the OpenAI Chat
Completions format, so any other compatible server works too: pick the closest provider and
pass `--base-url`.

Cloud providers need `--model`. The model must support **tool calling**; most current chat
models do.

## API keys
Keys are read **only from environment variables**, never from flags, so they don't end up in
your shell history. Set one for the current terminal session:

```text
set GROQ_API_KEY=gsk_...            (Windows cmd)
$env:GROQ_API_KEY = "gsk_..."       (PowerShell)
export GROQ_API_KEY=gsk_...         (bash)
```

Several providers have free tiers with rate limits. When a provider says you're sending too
much, the error says `429 (rate limited)`.

## Prompt caching with Claude
With `--provider anthropic`, the agent marks the system prompt, the tool definitions and the
newest message as cacheable. On the next step of the same task, everything before the new
message is read from Anthropic's cache instead of being processed again, which is cheaper and
faster. Nothing to configure; very short prompts (below a model-specific minimum) aren't cached.

## Local models: Ollama native vs. compatible
Prefer `ollama` over `ollama-openai`. The native API lets the agent set the context window
(8,192 tokens); through the compatible endpoint Ollama uses its default, **4,096 tokens** on this
setup, and quietly drops the oldest part of longer conversations. Switching between the two
also makes Ollama reload the model.
