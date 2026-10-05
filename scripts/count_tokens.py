"""Lesson 01: see how many tokens a piece of text costs.

Run:   python scripts/count_tokens.py "any text you like"
       python scripts/count_tokens.py --chat "Hi"     (also count the chat template's hidden tokens)
       python scripts/count_tokens.py                 (interactive: type lines, Ctrl+C to quit)

Trick: in "raw" mode Ollama skips the chat template and feeds our text straight
to the model. prompt_eval_count then tells us exactly how many tokens the text is.
"""
import sys

import httpx

MODEL = "qwen3:4b-instruct"
sys.stdout.reconfigure(encoding="utf-8")  # Windows terminals default to cp1252 and crash on non-English text


def count(text, chat=False):
    r = httpx.post("http://localhost:11434/api/generate", timeout=300, json={
        "model": MODEL,
        "prompt": text,
        "raw": not chat,                 # raw=True: no chat template, just our text
        "stream": False,
        "options": {"num_predict": 1},   # we only care about the input, so generate 1 token
    }).json()
    return r["prompt_eval_count"]


def show(text, chat):
    n = count(text, chat)
    label = "with chat template" if chat else "raw text"
    print(f"{n:>5} tokens  {len(text):>5} chars  {len(text) / n:4.1f} chars/token  ({label})  {text!r}")


args = sys.argv[1:]
chat = "--chat" in args
args = [a for a in args if a != "--chat"]

if args:
    show(" ".join(args), chat)
else:
    print(f"Type text to tokenize with {MODEL} (Ctrl+C to quit)")
    try:
        while True:
            line = input("> ")
            if line:
                show(line, chat)
    except (KeyboardInterrupt, EOFError):
        print()
