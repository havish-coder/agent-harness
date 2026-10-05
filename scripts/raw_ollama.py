"""Lesson 02: talk to an LLM over raw HTTP. No SDKs, no magic, just JSON.

Modes:
  python scripts/raw_ollama.py once "Why is the sky blue?"     one request; print the raw request and response JSON
  python scripts/raw_ollama.py stream "Tell me a joke"         print tokens as they are generated
  python scripts/raw_ollama.py stream "Hi" --show-chunks       ...and show every raw NDJSON line
  python scripts/raw_ollama.py chat                            multi-turn chat: the world's smallest harness
  python scripts/raw_ollama.py openai "Hi"                     same model, OpenAI-compatible endpoint

Options: --model NAME  --max-tokens N  --temperature T  --url http://host:port
"""
import argparse
import json
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")  # Windows terminals default to cp1252 and crash on non-English text

# LLM calls are slow. Allow 10 s to connect, but up to 5 minutes of waiting for response data.
TIMEOUT = httpx.Timeout(300, connect=10)


def build_request(args, messages, stream):
    """The JSON body for Ollama's POST /api/chat."""
    options = {"num_ctx": 4096}
    if args.max_tokens is not None:
        options["num_predict"] = args.max_tokens
    if args.temperature is not None:
        options["temperature"] = args.temperature
    return {"model": args.model, "messages": messages, "stream": stream, "options": options}


def check(response):
    """Raise an error for 4xx/5xx statuses, keeping Ollama's error message."""
    if response.is_error:
        response.read()  # a streamed response must be read before its body is available
        response.raise_for_status()


def print_stats(final, ttft=None):
    """Summarise the metrics Ollama sends with the last response. Durations are in nanoseconds."""
    out_tokens = final.get("eval_count", 0)
    seconds = final.get("eval_duration", 0) / 1e9
    stats = [
        f"prompt tokens: {final.get('prompt_eval_count', 0)}",
        f"output tokens: {out_tokens}",
        f"{out_tokens / seconds:.1f} tokens/s" if seconds else "0 tokens/s",
        f"done_reason: {final.get('done_reason')}",
    ]
    if ttft is not None:
        stats.insert(0, f"first token after {ttft:.2f}s")
    print("  [" + " | ".join(stats) + "]")


# ── Mode 1: one request, one complete response ──────────────────────────────

def once(args):
    body = build_request(args, [{"role": "user", "content": args.prompt}], stream=False)
    print(f"REQUEST   POST {args.url}/api/chat")
    print(json.dumps(body, indent=2, ensure_ascii=False))

    start = time.perf_counter()
    r = httpx.post(f"{args.url}/api/chat", json=body, timeout=TIMEOUT)
    check(r)
    data = r.json()

    print(f"\nRESPONSE  HTTP {r.status_code}, after {time.perf_counter() - start:.1f}s")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print()
    print_stats(data)


# ── Mode 2: streaming, tokens arrive one by one ─────────────────────────────

def stream_reply(args, messages, show_chunks=False):
    """POST with stream=true and print tokens as they arrive.

    Returns (full_text, final_chunk, seconds_until_first_token).
    """
    body = build_request(args, messages, stream=True)
    start = time.perf_counter()
    ttft = None
    parts = []
    final = {}

    with httpx.stream("POST", f"{args.url}/api/chat", json=body, timeout=TIMEOUT) as r:
        check(r)
        for line in r.iter_lines():  # NDJSON: one complete JSON object per line
            if not line:
                continue
            if show_chunks:
                print(f"  chunk: {line}")
            chunk = json.loads(line)
            if "error" in chunk:  # errors can also arrive mid-stream, after HTTP 200
                raise RuntimeError(chunk["error"])

            token = chunk.get("message", {}).get("content", "")
            if token:
                if ttft is None:
                    ttft = time.perf_counter() - start
                parts.append(token)
                if not show_chunks:
                    print(token, end="", flush=True)  # flush, or Python buffers the text and it appears in bursts
            if chunk.get("done"):
                final = chunk

    print()
    return "".join(parts), final, ttft


def stream(args):
    _, final, ttft = stream_reply(args, [{"role": "user", "content": args.prompt}], args.show_chunks)
    print_stats(final, ttft)


# ── Mode 3: multi-turn chat, the world's smallest harness ───────────────────

def chat(args):
    """The model is stateless, so WE keep the history and re-send all of it every turn."""
    history = []
    print(f"Chatting with {args.model}. Commands: /history  /fake <text>  /reset  /bye")

    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user == "/bye":
            break
        if user == "/reset":
            history.clear()
            print("(history cleared: the model has forgotten everything)")
            continue
        if user == "/history":
            print(json.dumps(history, indent=2, ensure_ascii=False))
            continue
        if user.startswith("/fake "):
            history.append({"role": "assistant", "content": user[len("/fake "):]})
            print("(added an assistant message the model never actually wrote)")
            continue

        history.append({"role": "user", "content": user})
        print("model> ", end="", flush=True)
        text, final, ttft = stream_reply(args, history)
        history.append({"role": "assistant", "content": text})
        print_stats(final, ttft)


# ── Mode 4: the same model in a different dialect ───────────────────────────

def openai_compat(args):
    """Ollama also speaks the OpenAI format. Compare this JSON with `once` mode."""
    body = {"model": args.model, "messages": [{"role": "user", "content": args.prompt}]}
    if args.max_tokens is not None:
        body["max_tokens"] = args.max_tokens
    if args.temperature is not None:
        body["temperature"] = args.temperature

    print(f"REQUEST   POST {args.url}/v1/chat/completions")
    print(json.dumps(body, indent=2, ensure_ascii=False))
    r = httpx.post(f"{args.url}/v1/chat/completions", json=body, timeout=TIMEOUT)
    check(r)
    print(f"\nRESPONSE  HTTP {r.status_code}")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="Talk to an LLM over raw HTTP (Lesson 02).")
    p.add_argument("mode", choices=["once", "stream", "chat", "openai"])
    p.add_argument("prompt", nargs="?", help="your message (not used in chat mode)")
    p.add_argument("--model", default="qwen3:4b-instruct")
    p.add_argument("--max-tokens", type=int, help="stop generating after this many output tokens")
    p.add_argument("--temperature", type=float)
    p.add_argument("--show-chunks", action="store_true", help="stream mode: print every raw NDJSON line")
    p.add_argument("--url", default="http://localhost:11434")
    args = p.parse_args()
    if args.mode != "chat" and not args.prompt:
        p.error(f"mode '{args.mode}' needs a prompt")

    modes = {"once": once, "stream": stream, "chat": chat, "openai": openai_compat}
    try:
        modes[args.mode](args)
    except httpx.ConnectError:
        sys.exit(f"\nERROR: cannot connect to {args.url}. Is Ollama running?")
    except httpx.TimeoutException:
        sys.exit("\nERROR: the model took too long to respond (timeout).")
    except httpx.HTTPStatusError as e:
        sys.exit(f"\nERROR: HTTP {e.response.status_code} from the server: {e.response.text}")
    except RuntimeError as e:
        sys.exit(f"\nERROR from the model server: {e}")


if __name__ == "__main__":
    main()
