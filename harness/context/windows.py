"""Lessons 36 and 59: how big is the model's context window?

Ollama's window is whatever `num_ctx` we ask for (the `context_window` setting). Cloud models have
fixed windows, which this table lists by model-name prefix. It is a starting point, not an authority:
a model not listed gets a cautious default, and the `context_window` setting overrides everything.
"""
import os
from urllib.parse import urlsplit

from harness.context.hardware import FLOOR, auto_window, model_facts, usable_memory

UNKNOWN_CLOUD_WINDOW = 32_000        # unknown model: assume little, so that we compact early rather than overflow

WINDOWS = [                           # (model name prefix, tokens), most specific first
    ("claude-", 200_000),
    ("gpt-4.1", 1_000_000), ("gpt-4o", 128_000), ("gpt-4-turbo", 128_000), ("gpt-5", 400_000), ("o1", 200_000), ("o3", 200_000),
    ("o4", 200_000), ("gemini-1.5-pro", 2_000_000), ("gemini-", 1_000_000),
    ("llama-3.1", 128_000), ("llama-3.3", 128_000), ("llama3", 8_192), ("llama-3", 8_192), ("mixtral", 32_000),
    ("qwen", 32_000), ("deepseek", 64_000),
]


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def resolve_window(provider: str, model: str | None, setting, base_url: str | None = None) -> tuple[int, str]:
    """(window, why), Lesson 59. A number is the user's; "auto" (the default) measures for a local Ollama model (harness/context/hardware.py)
    and uses the table for a cloud model."""
    if setting != "auto":
        return setting, f"set to {setting:,}"
    if provider == "ollama":
        if urlsplit(base_url or "http://localhost").hostname not in LOCAL_HOSTS:
            return FLOOR, "auto: 8,192 (the Ollama server is on another computer: its GPU can't be measured from here)"
        flash = os.environ.get("OLLAMA_FLASH_ATTENTION", "").strip().lower() in ("1", "true")      # a quantized cache needs it on
        cache = os.environ.get("OLLAMA_KV_CACHE_TYPE", "f16").strip().lower() if flash else "f16"
        return auto_window(model_facts(model or "qwen3:4b-instruct", base_url), usable_memory(base_url), cache)
    if provider in ("lmstudio", "ollama-openai"):
        return FLOOR, "auto: 8,192 (this server doesn't say how big its model is)"
    size = window_for(provider, model, FLOOR, False)
    return size, f"auto: {size:,} " + ("(assumed: an unknown cloud model)" if size == UNKNOWN_CLOUD_WINDOW else "(the model's window)")


def window_for(provider: str, model: str | None, configured: int, configured_explicitly: bool) -> int:
    """The window to plan for. An explicit `context_window` setting always wins; Ollama uses the setting
    (its default is 8192); a cloud model uses the table."""
    if configured_explicitly or provider in ("ollama", "lmstudio", "ollama-openai"):
        return configured
    name = (model or "").lower()
    return next((size for prefix, size in WINDOWS if name.startswith(prefix)), UNKNOWN_CLOUD_WINDOW)
