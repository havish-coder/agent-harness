"""Lesson 36: how big is the model's context window?

Ollama's window is whatever `num_ctx` we ask for (the `context_window` setting). Cloud models have
fixed windows, which this table lists by model-name prefix. It is a starting point, not an authority:
a model not listed gets a cautious default, and the `context_window` setting overrides everything.
"""
UNKNOWN_CLOUD_WINDOW = 32_000        # unknown model: assume little, so that we compact early rather than overflow

WINDOWS = [                           # (model name prefix, tokens), most specific first
    ("claude-", 200_000),
    ("gpt-4.1", 1_000_000), ("gpt-4o", 128_000), ("gpt-4-turbo", 128_000), ("gpt-5", 400_000), ("o1", 200_000), ("o3", 200_000),
    ("o4", 200_000), ("gemini-1.5-pro", 2_000_000), ("gemini-", 1_000_000),
    ("llama-3.1", 128_000), ("llama-3.3", 128_000), ("llama3", 8_192), ("llama-3", 8_192), ("mixtral", 32_000),
    ("qwen", 32_000), ("deepseek", 64_000),
]


def window_for(provider: str, model: str | None, configured: int, configured_explicitly: bool) -> int:
    """The window to plan for. An explicit `context_window` setting always wins; Ollama uses the setting
    (its default is 8192); a cloud model uses the table."""
    if configured_explicitly or provider in ("ollama", "lmstudio", "ollama-openai"):
        return configured
    name = (model or "").lower()
    return next((size for prefix, size in WINDOWS if name.startswith(prefix)), UNKNOWN_CLOUD_WINDOW)
