# 0058. The context window is sized for your GPU unless you set it, and can change while you work

- **Status:** Accepted
- **Date:** 2026-10-13

## Context
Since Lesson 36 a local model's window was the `context_window` setting, 8,192 by default ([ADR 0033](0033-estimate-context-and-refuse-overflow.md)).
That suits a 4 GB GPU like the one this project was built on, and wastes a bigger one: a user with 12 GB got the same 8K and had to find
the setting in the context guide. Changing it meant restarting the session.

What the window costs is known exactly. Ollama keeps the model's weights and its KV cache in GPU memory when they fit, and the cache per
token is `2 × layers × KV heads × head size × bytes per number`. For `qwen3:4b-instruct` that is 2 × 36 × 8 × 128 × 2 = 147,456 bytes, 1.21
GB per 8K. Weights 2.5 GB + cache 1.21 GB + about 0.4 GB of buffers is the 4.13 GB `ollama ps` reported at 8K
([the context guide](../user-guide/context.md#make-room-for-it-in-memory-ollama) measured what doesn't fit: at 32K on a 4 GB GPU, 27% on
the GPU and 0.7 tokens/s once full).

## Options
1. **Keep 8,192 and document bigger windows** (as before). Simple, and every user with a bigger GPU is slowed by the smallest one's default.
2. **Ask at first start**: "how much GPU memory do you have?" One more question, often answered wrong, and stale after a new GPU.
3. **Measure**: read the GPU's free memory and the model's shape, and pick the biggest window that keeps the whole model on the GPU.
4. **Use the model's maximum** (262,144 for `qwen3:4b-instruct`): doesn't fit anywhere but a big GPU, and spills to the CPU silently.

## Decision
Option 3 as the default (`context_window: "auto"`), with a number always winning, and a command to change it while you work.

- `harness/context/hardware.py`:
  - **The GPU's memory**: free and total come from `nvidia-smi`; on Apple silicon, two thirds of `hw.memsize`. Whatever Ollama's loaded
    models hold is added back (`/api/ps` `size_vram`), because Ollama unloads them to make room.
  - **The model's shape**: layers, KV heads, head size and maximum window from `/api/show`, the size of its weights from `/api/tags`.
  - **The size**: the largest multiple of 8,192 where weights + cache + 0.4 GB fit. Never below 8,192, never above the model's limit or
    131,072. `OLLAMA_KV_CACHE_TYPE` counts (1 byte for `q8_0`, half for `q4_0`) only if `OLLAMA_FLASH_ATTENTION` is on, as in Ollama.
- `harness/context/windows.py` `resolve_window`: a number is used as it is. For a local Ollama server, "auto" measures. For a remote one, LM
  Studio or an OpenAI-compatible server, it gives 8,192, because their GPU or model can't be measured from here. A cloud model keeps its
  table.
- **The session records why.** For example "auto: 8,192: a bigger window wouldn't fit beside qwen3:4b-instruct (2.3 GB) on your 4.0 GB GPU,
  so part of the model runs on the CPU". It is printed at start, and shown by `/context`, `/window` and the Settings drawer.
- **`/window [N|16k|auto]`** and the Settings drawer change it live. `Session.set_window` rebuilds the provider (Ollama's `num_ctx`) and
  the fallback, the budget (its calibration is kept), the prompt (its share grows with the window) and tool search, and audits the change.
  Shrinking below the conversation is safe: the next request clears old results to fit, which a test checks.
- **Tests never probe this machine**: an autouse fixture makes "auto" see nothing (8,192), and `tests/test_hardware.py` fakes `nvidia-smi`
  and Ollama.

What auto picks for `qwen3:4b-instruct`, with the whole GPU free: 4 GB → 8,192 (16,384 with an 8-bit cache), 8 GB → 32,768, 12 GB →
65,536, 16 GB → 90,112, 24 GB → 131,072. On this laptop it keeps 8,192, as before.

Checked live on this laptop: auto kept 8,192 with the reason above. After `/window 16k` the next request ran at 16,384 without a
restart: Ollama's `/api/ps` reported a 16,384 context, and the model's memory went from 3.85 to 5.03 GB, what the formula predicts.

## Consequences
- A bigger GPU gets a bigger window with no setting, and the start-up line says what it got and why.
- Auto measures once, at start. Memory that another program takes later isn't seen (`/window auto` measures again). Free memory, not
  total, is the input: a desktop using 1 GB of the GPU gets a smaller window than a headless server with the same card.
- It assumes the model's weights all go on the GPU, and only the first NVIDIA GPU is counted. Ollama can split a model across GPUs; auto
  is then conservative.
- A number in the settings is now the way to get a window that doesn't fit, knowingly. The context guide's tables show what that costs.
