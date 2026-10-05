"""Lesson 01: check that everything the course needs is installed and working.

Run:   python scripts/check_setup.py              (checks qwen3:4b-instruct)
       python scripts/check_setup.py qwen3:4b     (checks another model)

You don't need to understand the HTTP calls yet. Lesson 02 covers them properly.
"""
import sys

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3:4b-instruct"
OLLAMA = "http://localhost:11434"
sys.stdout.reconfigure(encoding="utf-8")  # Windows terminals default to cp1252 and crash on non-English text


def ok(msg):
    print(f"  [OK]   {msg}")


def fail(msg, fix):
    print(f"  [FAIL] {msg}\n         fix: {fix}")
    sys.exit(1)


print("Checking your setup...\n")

# 1. Python version
if sys.version_info < (3, 10):
    fail(f"Python {sys.version.split()[0]}", "install Python 3.10 or newer")
ok(f"Python {sys.version.split()[0]}")

# 2. httpx, our only dependency for talking to LLMs
try:
    import httpx
except ImportError:
    fail("httpx is not installed", 'activate the venv, then run: pip install -e ".[dev]"')
ok(f"httpx {httpx.__version__}")

# 3. Is the Ollama server running?
try:
    version = httpx.get(f"{OLLAMA}/api/version", timeout=5).json()["version"]
except httpx.HTTPError:
    fail(f"Ollama server not reachable at {OLLAMA}", "start the Ollama app (or run: ollama serve)")
ok(f"Ollama server {version}")

# 4. Is the model downloaded?
names = [m["name"] for m in httpx.get(f"{OLLAMA}/api/tags", timeout=5).json()["models"]]
if MODEL not in names:
    fail(f"model {MODEL} is not downloaded", f"ollama pull {MODEL}")
ok(f"model {MODEL} is downloaded")

# 5. What can the model do? /api/show returns its metadata.
info = httpx.post(f"{OLLAMA}/api/show", json={"model": MODEL}, timeout=30).json()
caps = info.get("capabilities", [])
max_ctx = next((v for k, v in info.get("model_info", {}).items() if k.endswith(".context_length")), "?")
if "tools" not in caps:
    fail(f"{MODEL} does not support tool calling", "use a tool-capable model, e.g. qwen3:4b-instruct")
ok(f"capabilities: {', '.join(caps)}")
d = info["details"]
ok(f"{d['parameter_size']} parameters, {d['quantization_level']} quantization, max context {max_ctx} tokens")

# 6. A real request, with token counts and speed
print("\n  Asking the model a question (the first run loads it into memory, which can take a while)...")
r = httpx.post(f"{OLLAMA}/api/chat", timeout=300, json={
    "model": MODEL,
    "stream": False,
    "messages": [{"role": "user", "content": "Reply with exactly: setup works"}],
}).json()
speed = r["eval_count"] / (r["eval_duration"] / 1e9)
ok(f'model replied: "{r["message"]["content"].strip()}"')
ok(f"prompt tokens: {r.get('prompt_eval_count', '?')} | output tokens: {r['eval_count']} | speed: {speed:.1f} tokens/s")

print("\nAll good! You're ready for Lesson 02.")
