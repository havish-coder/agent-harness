# 0014. One OpenAI-compatible adapter for cloud models; keys only from the environment

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Users should be able to run the agent on a cloud model. There are many vendors, but most of
them (OpenAI, Groq, OpenRouter, Together, Mistral, DeepSeek, Gemini's compatibility endpoint)
and most local servers (LM Studio, vLLM, llama.cpp, Ollama's `/v1`) accept OpenAI's Chat
Completions format. Cloud providers need API keys, which are secrets.

## Options
1. **One adapter per vendor**: best fidelity; many adapters to maintain.
2. **One OpenAI-compatible adapter** plus a table of known services (base URL, key variable),
   and native adapters only where they add something essential (Ollama's context-size option,
   Anthropic's format and caching).
3. **Keys from flags or config files**: convenient; keys leak into shell history, process
   listings and commits.
4. **Keys only from environment variables.**

## Decision
Options 2 and 4. `OpenAICompatProvider` implements Chat Completions with SSE streaming;
`make_provider()` maps provider names to base URLs and key variables. Keys are read from
environment variables only, and never shown in `repr()` or errors.

## Consequences
- One adapter covers the ecosystem; it was tested live against Ollama's `/v1` endpoint (12/12
  on the agent's question set, the same as the native adapter).
- Vendor extensions beyond the common format (reasoning fields, provider-specific caching) are
  not available through it.
- Ollama through `/v1` can't set the context window (4,096 tokens by default here), so the
  native adapter stays the default for Ollama.
