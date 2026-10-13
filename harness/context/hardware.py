"""Lesson 59: how big a context window fits this computer.

Ollama keeps a model's weights and its KV cache (what the model has read so far) in the GPU's memory when they fit. The cache grows
with the window:

    cache bytes per token = 2 (keys and values) × layers × KV heads × head size × bytes per number

qwen3:4b-instruct: 2 × 36 × 8 × 128 × 2 = 147,456 bytes a token, 1.21 GB per 8,192 tokens. With its 2.5 GB of weights and about 0.4 GB
of buffers that is 4.1 GB at 8K: what `ollama ps` reported (4.13 GB) and what the context guide measured.

`auto_window` picks the largest window, in steps of 8,192, whose weights + cache + buffers fit in the GPU memory Ollama can use, so the
whole model stays on the GPU, which is what keeps answers fast. Never below 8,192 (what a small GPU always ran, partly on the CPU), never
above the model's own limit or 131,072. Anything it can't find out (no NVIDIA GPU or Apple silicon, a remote server, an unknown
model) gives 8,192. The size is a starting point: `/window` changes it, and a number in the settings always wins.
"""
import platform
import subprocess
from dataclasses import dataclass

import httpx

STEP = 8_192
FLOOR = 8_192
CEILING = 131_072              # ponytail: bigger windows are slow to fill and rarely needed; a number in the settings goes higher
BUFFERS = 400 * 2**20          # compute buffers beside weights and cache, about 0.4 GB (4.13 GB measured - 2.5 - 1.21)
BYTES = {"f16": 2, "q8_0": 1, "q4_0": 0.5}         # per number in the cache, by OLLAMA_KV_CACHE_TYPE


@dataclass
class ModelFacts:
    name: str
    max_window: int
    layers: int
    kv_heads: int
    head_size: int
    weights: int               # bytes

    def per_token(self, cache_type: str = "f16") -> float:
        return 2 * self.layers * self.kv_heads * self.head_size * BYTES.get(cache_type, 2)


def gb(n: float) -> str:
    return f"{n / 2**30:.1f} GB"


def run(*command: str) -> str:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=5)
        return done.stdout if done.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def gpu_memory() -> tuple[int, int] | None:
    """(free, total) bytes of the first NVIDIA GPU, or of Apple silicon's shared memory; None when neither is found."""
    line = run("nvidia-smi", "--query-gpu=memory.free,memory.total", "--format=csv,noheader,nounits").strip().splitlines()
    try:
        if line:
            free, total = (int(x) * 2**20 for x in line[0].split(","))     # MiB; ponytail: the first GPU only
            return free, total
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            total = int(run("sysctl", "-n", "hw.memsize").strip())
            return total * 2 // 3, total           # Metal lets one process use about two thirds of the shared memory
    except ValueError:
        pass
    return None


def ollama(base_url: str | None, path: str, body: dict | None = None) -> dict:
    url = (base_url or "http://localhost:11434").rstrip("/") + path
    try:
        r = httpx.post(url, json=body, timeout=5) if body is not None else httpx.get(url, timeout=5)
        return r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}


def model_facts(model: str, base_url: str | None = None) -> ModelFacts | None:
    """What the window's cost depends on, from Ollama's /api/show and /api/tags; None when it doesn't say."""
    info = ollama(base_url, "/api/show", {"model": model}).get("model_info") or {}

    def find(suffix):
        value = next((v for k, v in info.items() if k.endswith(suffix)), None)
        return max(value) if isinstance(value, list) and value else value          # some models list a value per layer
    layers, kv_heads, max_window = find(".block_count"), find(".attention.head_count_kv"), find(".context_length")
    head_size = find(".attention.key_length")
    if head_size is None and find(".embedding_length") and find(".attention.head_count"):
        head_size = find(".embedding_length") // find(".attention.head_count")
    names = {model, model if ":" in model else model + ":latest"}
    weights = next((m.get("size") for m in ollama(base_url, "/api/tags").get("models", []) if m.get("name") in names), None)
    if not all(isinstance(v, int) and v > 0 for v in (layers, kv_heads, max_window, head_size, weights)):
        return None
    return ModelFacts(model, max_window, layers, kv_heads, head_size, weights)


def usable_memory(base_url: str | None = None) -> tuple[int, int] | None:
    """(bytes the model may use, total): the GPU's free memory plus what Ollama's loaded models hold (they are unloaded to make room)."""
    gpu = gpu_memory()
    if gpu is None:
        return None
    free, total = gpu
    held = sum(m.get("size_vram") or 0 for m in ollama(base_url, "/api/ps").get("models", []))
    return min(free + held, total), total


def auto_window(facts: ModelFacts | None, memory: tuple[int, int] | None, cache_type: str = "f16") -> tuple[int, str]:
    """(window, why): the largest step of 8,192 that keeps the whole model on the GPU, within [8,192, the model's limit or 131,072]."""
    if facts is None:
        return FLOOR, "auto: 8,192 (the model's size isn't known: Ollama didn't say)"
    floor = min(FLOOR, facts.max_window)
    if memory is None:
        return floor, f"auto: {floor:,} (no GPU memory found to fit a bigger window in)"
    usable, total = memory
    room = usable - facts.weights - BUFFERS
    fits = int(room // facts.per_token(cache_type)) // STEP * STEP if room > 0 else 0
    window = min(fits, facts.max_window, CEILING)
    if window < floor:
        return floor, (f"auto: {floor:,}: a bigger window wouldn't fit beside {facts.name} ({gb(facts.weights)}) on your {gb(total)} GPU, "
                       "so part of the model runs on the CPU")
    capped = " (the model's limit)" if window == facts.max_window else " (the harness's ceiling; set a number to go higher)" if window == CEILING else ""
    return window, f"auto: {window:,}{capped}, fits beside {facts.name} on your {gb(total)} GPU ({gb(usable)} usable, {cache_type} cache)"
