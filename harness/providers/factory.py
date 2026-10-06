"""Lesson 17: build a provider from a name and settings, so interfaces don't import adapters.

API keys come from environment variables, never from command-line flags (which end up in
shell history and process listings) or committed files. Lesson 20 adds config files.
"""
import os

from harness.providers.base import Provider, ProviderError

# Known OpenAI-compatible services: name → (base URL, environment variable holding the key)
OPENAI_COMPATIBLE = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "lmstudio": ("http://localhost:1234/v1", None),
    "ollama-openai": ("http://localhost:11434/v1", None),   # Ollama's compatibility endpoint
}
PROVIDERS = ["ollama", "anthropic", *OPENAI_COMPATIBLE]


def make_provider(name: str = "ollama", model: str | None = None, base_url: str | None = None, *,
                  temperature: float | None = None, think: bool | None = None,
                  context_window: int | None = None, max_output_tokens: int | None = None) -> Provider:
    """Create a provider. Options a backend doesn't support are ignored."""
    if name == "ollama":
        from harness.providers.ollama import OllamaProvider
        kwargs = {"url": base_url} if base_url else {}
        if context_window:
            kwargs["num_ctx"] = context_window
        return OllamaProvider(model=model or "qwen3:4b-instruct", temperature=temperature, think=think,
                              num_predict=max_output_tokens, **kwargs)
    if name == "anthropic":
        from harness.providers.anthropic import AnthropicProvider
        kwargs = {"base_url": base_url} if base_url else {}
        if max_output_tokens:
            kwargs["max_tokens"] = max_output_tokens
        return AnthropicProvider(model=model or "claude-sonnet-5-5", api_key=os.environ.get("ANTHROPIC_API_KEY"),
                                 temperature=temperature, **kwargs)
    if name in OPENAI_COMPATIBLE:
        from harness.providers.openai_compat import OpenAICompatProvider
        default_url, key_var = OPENAI_COMPATIBLE[name]
        api_key = os.environ.get(key_var) if key_var else None
        if key_var and not api_key:
            raise ProviderError(f"provider '{name}' needs an API key: set the {key_var} environment variable")
        if not model:
            raise ProviderError(f"provider '{name}' needs a model name (--model)")
        return OpenAICompatProvider(model, base_url=base_url or default_url, api_key=api_key, temperature=temperature,
                                    max_tokens=max_output_tokens)
    raise ProviderError(f"unknown provider '{name}'. Known: {', '.join(PROVIDERS)}")
