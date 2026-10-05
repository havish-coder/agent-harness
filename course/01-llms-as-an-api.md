# Lesson 01 · LLMs as an API

> **Module 0: Foundations** · What actually happens inside one model call, from your
> `messages` down to tokens. Then we set up the dev environment.

## Learning objectives
By the end of this lesson you can:
1. Explain what tokens are and why a harness counts them.
2. Explain the context window and what happens when a conversation overflows it.
3. Describe the four message roles and how a **chat template** flattens them (and
   the tools!) into one long string.
4. Use sampling settings (temperature, seed...) and choose good ones for an agent.
5. Explain what a "thinking" model does differently.
6. Run a working setup: venv, `httpx`, Ollama, `qwen3:4b-instruct`.

---

## 1. Learn

### 1.1 The journey of one request

```
 messages[]                          the model only ever sees ONE long sequence of numbers
 ┌──────────────┐   chat      ┌────────────────────────────┐  tokenizer  ┌──────────────────────┐
 │ system: ...  │ ─template─► │ <|im_start|>system\n...    │ ──────────► │ 151644, 8948, 198,   │
 │ user:   ...  │             │ <|im_start|>user\nHi...    │             │ 2610, 525, 1207, ... │
 └──────────────┘             └────────────────────────────┘             └──────────┬───────────┘
                                                                                    │
                                                                                    ▼
 text / tool_calls ◄── detokenizer ◄── [9707, 0, ...] ◄── predict ONE token, append it, repeat
```

Every arrow in that picture is something a harness builder needs to understand:
- **Chat template**: how roles and tools become text (section 1.4)
- **Tokenizer**: how text becomes numbers, which sets cost and limits (1.2, 1.3)
- **Predict one token, repeat**: generation is a loop, steered by sampling (1.6)

### 1.2 Tokens

Models don't read characters or words. They read **tokens**: chunks from a fixed
vocabulary (Qwen models have about 151,000). Common words are a single token. Rare words
get split into pieces. Each token is an integer ID.

Measured on your machine with the Qwen tokenizer (`scripts/count_tokens.py`):

| Text | Characters | Tokens |
|---|---:|---:|
| `hello` / ` hello` / `Hello` | 5-6 | 1 each |
| `HELLO` | 5 | 2 |
| `The quick brown fox jumps over the lazy dog.` | 44 | 10 |
| `antidisestablishmentarianism` | 28 | 6 |
| `def add(a, b):⏎    return a + b` | 31 | 11 |
| `नमस्ते दुनिया` (Hindi, "hello world") | 13 | 13 |
| `வணக்கம் உலகம்` (Tamil, "hello world") | 13 | 13 |
| `🙂🙂🙂` | 3 | 3 |
| `12345678901234567890` | 20 | 20 |

Patterns to remember:
- English averages **about 4 characters per token** (about ¾ of a word).
- Qwen splits numbers into **one token per digit**. The model never sees "1234" as a
  quantity, only as four symbols. That's one reason LLMs are unreliable at arithmetic,
  and why agents get a calculator or code tool instead of doing math "in their head".
- Many non-English scripts cost **about 1 token per character**. The same sentence can
  cost 3-4× more in Hindi or Tamil than in English, because the tokenizer saw mostly
  English during training.
- Code spends tokens on punctuation and indentation.

**Why a harness builder cares about tokens:**
1. **Limits.** The context window is measured in tokens (next section).
2. **Speed.** Output is generated one token at a time. Your GPU manages some number of
   tokens per second, and a 500-token answer takes 500 steps.
3. **Money.** Cloud APIs bill per token, input and output priced separately. Local
   models are free but cost time.

### 1.3 The context window

The **context window** is the most tokens one call can involve: **input + output combined**.
Everything shares it:

```
┌─────────────────────────── context window (e.g. 4,096 tokens) ───────────────────────────┐
│ system prompt │ tool definitions │ conversation history │ tool results │ reply being written │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

Two different numbers matter:
- **The model's maximum.** What it was trained to handle. `qwen3:4b` supports **262,144** tokens.
- **What Ollama actually allocates (`num_ctx`).** Usually much smaller, because every token
  of context needs GPU memory (the "KV cache"). On your machine Ollama loaded `qwen3:4b`
  with just **4,096** tokens, which is **1.5%** of what the model can handle. You can see
  this in the `CONTEXT` column of `ollama ps`. Our harness will set `num_ctx` explicitly.

**What happens when a conversation doesn't fit?**
- **Ollama** quietly cuts older parts of the conversation so the rest fits. There's **no
  error**, and the model simply never sees what was cut. You'll prove this in Experiment 5.
- **Cloud APIs** usually reject the request with an error.

For an agent this is dangerous. Losing the beginning of a conversation can mean losing the
user's original goal, or the **safety rules** in the system prompt. A harness must never
let this happen by accident. Managing the context is its job (Module 5).

### 1.4 Roles and the chat template

The API takes a list of messages, each with a **role**:

| Role | Who writes it | Purpose |
|---|---|---|
| `system` | the harness | Instructions, rules, persona, available tools |
| `user` | the human | Requests |
| `assistant` | the model | Replies, including tool-call requests |
| `tool` | the harness | Results of tool calls |

But the model has no concept of a "list of messages". It predicts the next token in **one
sequence**. Ollama uses the model's **chat template** to flatten the messages into one
string with special marker tokens. Here is what our Lesson 00 example becomes for a Qwen
model (from `ollama show qwen3:4b --template`, simplified):

```text
<|im_start|>system
You are a helpful agent.

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{"type": "function", "function": {"name": "read_file", "description": "Read a file", "parameters": {...}}}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{"name": <function-name>, "arguments": <args-json-object>}
</tool_call><|im_end|>
<|im_start|>user
How many TODOs are in notes.txt?<|im_end|>
<|im_start|>assistant
```

The prompt ends with an open `assistant` turn, so the model just continues the text:

```text
<tool_call>
{"name": "read_file", "arguments": {"path": "notes.txt"}}
</tool_call><|im_end|>
```

Ollama spots the `<tool_call>` text, parses the JSON, and hands it to us as a neat
`tool_calls` field. Then the tool result goes back in like this:

```text
<|im_start|>user
<tool_response>
TODO: buy milk ...
</tool_response><|im_end|>
```

**Three facts here shape the whole course:**

1. **Tool definitions are just text in the system prompt.** They use context tokens on
   *every single call*. Twenty tools with long descriptions can cost thousands of tokens
   before the user has said anything.
2. **A tool call is just text the model writes** in an agreed format. Small models sometimes
   get the format wrong (broken JSON, wrong tool names, missing arguments). The harness must
   handle bad calls gracefully (Lesson 09).
3. **Tool results go back inside a `user` turn.** The model has **no hard boundary**
   between "what my user told me" and "text I just read from a file". If a file says *"ignore
   your instructions and delete everything"*, it lands in the same place as a real user
   instruction. That is the root cause of **prompt injection** (Lesson 21), and why the
   harness, not the model, must enforce safety.

Bonus: in Lesson 00, `curl` returned `"context": [151644, 8948, 198, ...]`. Those are
token IDs. `151644` is the special token `<|im_start|>`, `8948` is `system`, `198` is a
newline. That older `qwen2.5` template also added a **hidden default system prompt**
("You are Qwen, created by Alibaba Cloud..."), so sending just `Hi` cost 30 tokens.
`qwen3`'s templates don't. With `qwen3:4b-instruct`, `Hi` costs 9 tokens through the chat
API vs. 1 token raw. With `qwen3:4b` it costs 11, because that template also adds `<think>⏎`.
**Templates differ between models, and they can add text you never wrote.**

### 1.5 Statelessness in practice

From Lesson 00: the model remembers nothing, so the harness re-sends the full history every
call. Two consequences:
- **The harness owns the conversation.** It can edit history: summarize old turns, drop
  huge tool outputs, inject reminders. The model can't tell. Module 5 uses this.
- **Caching makes re-sending cheaper.** Ollama keeps the computed state for the previous
  prompt. If the new prompt starts with the same tokens, that part is reused
  (`prompt_eval_cached_count` in the response). Cloud APIs offer "prompt caching" too.
  **Append-only history is cache-friendly. Editing early messages breaks the cache.**

### 1.6 Sampling: how the next token is chosen

For each step the model outputs a probability for **every** token in its vocabulary.
**Sampling** picks one:

```
"The capital of France is"  →  model  →   " Paris"  0.92  ██████████████████
                                          " the"    0.03  █
                                          " a"      0.02  ▌
                                          ...151k more, tiny probabilities

temperature 0    → always pick the top token     → " Paris", every time
temperature 1    → sample by probability          → " Paris" ~92% of the time
temperature 1.5  → flatten the odds               → more surprises
```

| Setting | What it does | Ollama option |
|---|---|---|
| temperature | randomness (0 = always the most likely token) | `temperature` |
| top_k / top_p | only sample from the top-k tokens, or the smallest set covering p probability | `top_k`, `top_p` |
| seed | fixes the randomness, so runs repeat exactly | `seed` |
| max tokens | cap on output length | `num_predict` |
| stop | stop generating when this text appears | `stop` |

**For agents:** tool calls must be valid JSON and decisions should be consistent, so we
want **low randomness**. One caveat: model makers publish recommended settings. Qwen3's
authors warn that fully greedy decoding (temperature 0) with thinking enabled can cause
endless repetition. We'll start from the model's defaults and lower the temperature for
tool-heavy work.

### 1.7 Thinking models, and a real bug we hit while building this lesson

A **thinking model** writes out its reasoning before answering. Ollama returns the reasoning
separately in `message.thinking` and the answer in `message.content`.

- **Pros:** better at multi-step problems, planning, and arithmetic.
- **Cons:** slower and uses more tokens (thinking tokens are output tokens too).

**What actually happened.** While writing this lesson, `scripts/check_setup.py` asked
`qwen3:4b` to *"Reply with exactly: setup works"* and passed `"think": false` to turn
thinking off. The reply took **231 tokens** and looked like this:

```text
Hmm, the user just asked me to reply with exactly "setup works"... [200 more tokens]
</think>

setup works
```

The thinking **leaked into `content`**. Why? Experiment 3 has you read the template,
which always ends with:

```text
<|im_start|>assistant
<think>
```

This `qwen3:4b` build is a **thinking-only** model: the template *forces* a `<think>` block
on every reply. Our `think: false` flag only told Ollama to stop separating the thinking out.
It couldn't stop the thinking itself.

**Lessons for harness builders:**
1. **Don't trust flags; read the template.** The template decides what the model really sees.
2. **Model choice is a harness decision.** An agent may call the model 10+ times per task.
   About 200 thinking tokens per call at about 15 tokens/s adds **13+ seconds per step**.
3. **Program defensively.** Real harnesses strip stray `<think>` blocks from output.

So the course uses **two** models:

| Model | Thinking | Used for |
|---|---|---|
| `qwen3:4b-instruct` | none, answers directly | **the course's default**: fast agent steps |
| `qwen3:4b` | always on | comparison experiments, and later as a "planner" for hard tasks |

### 1.8 Model size, quantization and your GPU

A 4B model has 4 billion parameters (numbers). At 16 bits each that's 8 GB, too big for
your 4 GB GPU. Ollama ships it **quantized** to about 4 bits per number (`Q4_K_M`), so the
weights are about 2.5 GB.

But weights aren't everything. Measured on your machine, `ollama ps` showed:

```text
NAME        SIZE      PROCESSOR          CONTEXT
qwen3:4b    3.5 GB    36%/64% CPU/GPU    4096
```

Loaded, it's **3.5 GB**: weights, plus the KV cache for 4,096 tokens of context, plus
working memory. Windows also uses some of your 4 GB of VRAM for the display. So **36% of the
model runs on the CPU**, which is why we measured only about 15-22 tokens/s. Same-size models fully on a GPU run several times faster.
`gpt-oss:20b` (13 GB) would be mostly CPU and far slower. **Raising `num_ctx` costs VRAM**,
which pushes more onto the CPU. It's a trade-off our harness will let you tune.

---

## 2. Build

| File | What it is |
|---|---|
| `.gitignore` | Keeps `.venv/`, caches and **`.env` (secrets)** out of git. API keys must never be committed. |
| `pyproject.toml` | Project metadata. One runtime dependency: **`httpx`** (an HTTP client with timeouts and streaming, all we need to talk to an LLM). `pytest` is for testing. |
| `harness/__init__.py` | The empty Python package where the harness will live, starting Lesson 04. |
| `scripts/check_setup.py` | Checks Python, `httpx`, the Ollama server, the model, its capabilities, and does a real call with speed and token counts. |
| `scripts/count_tokens.py` | Token explorer: type any text and see what it costs. |

The virtual environment is already created and the packages installed. **To use it** in a
PowerShell terminal in this folder:

```bash
.venv\Scripts\Activate.ps1
```

Your prompt now starts with `(.venv)`, and `python` means the project's Python.
If PowerShell says *"running scripts is disabled"*, skip activation and type
`.venv\Scripts\python` instead of `python` in every command.

*(On a fresh machine you'd create the venv yourself with `python -m venv .venv`, then
`pip install -e ".[dev]"`. `-e` means "editable": changes to `harness/` take effect without
reinstalling.)*

---

## 3. Understand: walkthrough + experiments

### Code walkthrough
Open `scripts/check_setup.py`. It uses four Ollama endpoints. You'll meet them properly in
Lesson 02:

| Endpoint | Used for |
|---|---|
| `GET /api/version` | Is the server alive? |
| `GET /api/tags` | Which models are downloaded? |
| `POST /api/show` | Model metadata: capabilities (`tools`, `thinking`), max context, quantization |
| `POST /api/chat` | An actual chat call. The response includes `prompt_eval_count` (input tokens), `eval_count` (output tokens), and `eval_duration` (nanoseconds), which gives tokens/second. |

Then open `scripts/count_tokens.py`. The trick is `"raw": True`, which tells Ollama to
**skip the chat template** and feed our text in untouched. `prompt_eval_count` is then
exactly the token count of our text. With `--chat`, the template is applied, so you see its
overhead too.

### Experiment 1: Check your setup
```bash
python scripts/check_setup.py
```
Every line should say `[OK]`. Note your **tokens/s**. That's your model's typing speed.

### Experiment 2: Explore tokens
```bash
python scripts/count_tokens.py
```
Try:
- an English sentence, then the same sentence in your own language
- `hello` vs ` hello` (leading space) vs `Hello` vs `HELLO`
- a long number like `12345678901234567890`
- some JSON: `{"name": "read_file", "arguments": {"path": "notes.txt"}}`

Then compare raw vs templated:
```bash
python scripts/count_tokens.py "Hi"
```
```bash
python scripts/count_tokens.py --chat "Hi"
```
The difference is the template's overhead (marker tokens and any default system prompt).

### Experiment 3: Read the real chat template
```bash
ollama show qwen3:4b --template
```
It's written in Go's template language. Don't worry about the syntax. Find:
1. Where the system message goes.
2. Where the **tools** get injected, and the instructions telling the model how to call them.
3. **Which role a tool result is wrapped in.** (You read why that matters in 1.4.)
4. The very last line. What does it force every reply to start with? (Section 1.7.)

Then try `ollama show qwen3:4b-instruct --template`. It's a different syntax (Jinja, the
format Hugging Face uses), and its last line opens the assistant turn **without** `<think>`.

### Experiment 4: Feel the temperature
```bash
ollama run qwen3:4b-instruct
```
Then type these lines one at a time. `/clear` wipes the history between tries:
```text
/set parameter temperature 0
Invent a name for a pet robot. Reply with one word only.
/clear
Invent a name for a pet robot. Reply with one word only.
/clear
/set parameter temperature 1.5
Invent a name for a pet robot. Reply with one word only.
/clear
Invent a name for a pet robot. Reply with one word only.
```
At 0 the answers repeat. At 1.5 they vary. Type `/bye` to exit.

### Experiment 5: Overflow the context window
```bash
ollama run qwen3:4b-instruct
```
```text
/set parameter num_ctx 256
My secret code is PINEAPPLE-42. Just reply OK.
Write a 300-word story about a lighthouse.
What was my secret code?
```
With only 256 tokens of context, the start of the conversation was silently dropped to
make room. The model can't answer. **No error, no warning.** Now imagine that dropped text
was the agent's safety rules. Type `/bye` to exit.

<details><summary>What we measured</summary>

Running the same conversation through the API:
- `num_ctx=4096`: the last call sent 574 prompt tokens, and the model answered **PINEAPPLE-42**.
- `num_ctx=256`: the model saw only **14 prompt tokens**. Everything except the last
  question had been dropped. It answered *"I'm sorry, but I don't know what your secret code
  might be."* Worse, while writing the story it also lost the instruction "300 words" and
  rambled on for **1,868 words**.
</details>

### Experiment 6: Thinking vs. no thinking
Ask both models an **easy** question and a **hard** one. `--verbose` prints timings after
the answer: compare `eval count` (output tokens) and `total duration`.
```bash
ollama run qwen3:4b-instruct --verbose "What is the capital of France? One word."
```
```bash
ollama run qwen3:4b --verbose "What is the capital of France? One word."
```
```bash
ollama run qwen3:4b-instruct --verbose "Is 3599 a prime number? Answer yes or no."
```
```bash
ollama run qwen3:4b --verbose "Is 3599 a prime number? Answer yes or no."
```
The hard question takes 1-2+ minutes per model on your GPU. Be patient.
Were they right? (3599 = 59 × 61, so it's **not** prime.) Was the thinking worth it for
the easy question?

<details><summary>What we measured on your machine while building this lesson</summary>

| Question | Model | Output tokens | Time | Correct? |
|---|---|---:|---:|---|
| Capital of France | `qwen3:4b-instruct` | 2 | 3.5 s | ✅ Paris |
| Capital of France | `qwen3:4b` (thinking) | 300 | 41.8 s | ✅ Paris |
| Is 3599 prime? | `qwen3:4b-instruct` | 1,013 | 74 s | ✅ No |
| Is 3599 prime? | `qwen3:4b` (thinking) | 1,490 | 143 s | ✅ "Yes, 3599 is **not** a prime" |

Takeaways:
- **Easy question:** thinking cost 150× more tokens for the same answer.
- **Hard question:** the instruct model *ignored* "answer yes or no" and reasoned out loud
  in its answer anyway (models think in tokens; there's no other way for them to work things
  out). Both were correct.
- The thinking model's final sentence, *"Yes, 3599 is not a prime"*, contradicts itself.
  Our harness will often need answers in an exact format, and this is why later lessons
  validate model output instead of trusting it.
</details>

### Experiment 7: What's loaded on your GPU?
Right after an experiment, while the model is still in memory, run:
```bash
ollama ps
```
Look at **PROCESSOR** (is it `100% GPU`?) and **CONTEXT** (that's `num_ctx`).

---

## 4. Review

### Quiz
1. Roughly how many tokens is a 3,000-word English document? Why would the same content
   in Hindi cost more?
2. Name at least four things that share the context window.
3. A long conversation overflows the context in Ollama. What can go wrong for an
   *agent*, and whose job is it to prevent it?
4. Are tool definitions "free"? If not, on which calls do they cost tokens?
5. For the Qwen template, tool results are placed inside a `user` turn. Why does that matter
   for security?
6. What temperature range suits an agent that must produce valid tool-call JSON, and why?

### Exercise 1 (pen and paper): the hidden cost of agents
An agent's system prompt plus tool definitions is **1,500 tokens**. The user's question is
**50 tokens**. On each step, the model writes a **50-token** tool call and gets back a
**400-token** tool result. It makes **8 tool calls**, then gives the final answer (so
**9 model calls** in total).

a) How many input tokens does the 1st call send? The 2nd? The 9th?
b) How many input tokens in total across all 9 calls?
c) At $3 per million input tokens, what does the run cost?
d) Redo (b) and (c) if each tool result is 4,000 tokens instead of 400.

### Exercise 2 (optional, code)
Add a step 7 to `scripts/check_setup.py`: call `GET /api/ps` (it returns the loaded models),
and print what percent of the model is on the GPU, using the `size` and `size_vram` fields.

### Checkpoint
- `python scripts/check_setup.py` shows all `[OK]`.
- You can explain why `Hi` costs more tokens through the chat API than as raw text, and
  why tool results arriving in a `user` turn is a security problem.

---

### Answers

<details><summary>Quiz answers</summary>

1. About 4,000 tokens (3,000 words ÷ 0.75 words per token). Hindi often costs about 1
   token per character because the tokenizer has fewer Hindi words in its vocabulary, so the
   same meaning needs several times more tokens.
2. System prompt, tool definitions, conversation history (user and assistant messages),
   tool results, and the output being generated.
3. Older content is silently dropped, possibly the user's original goal or the system
   prompt's safety rules, and the model carries on without them. Preventing it is the
   **harness's** job: count tokens and compact deliberately (Module 5).
4. Not free. They're text in the system prompt, so they're sent and counted on **every**
   call, as input tokens.
5. The model can't reliably tell the difference between instructions from its user and text
   that came out of a file or web page. Injected instructions in tool output sit in
   the same position as genuine user requests. So safety can't rely on the model "knowing
   better"; the harness must enforce it.
6. Low (about 0–0.3, or the model maker's recommended setting). We need precise, valid
   JSON and consistent decisions, not creativity. Lower randomness means fewer malformed calls.
</details>

<details><summary>Exercise 1 answers</summary>

a) Call 1: 1,500 + 50 = **1,550**. Each step adds 50 (tool call) + 400 (result) = 450.
   Call 2: **2,000**. Call 9: 1,550 + 8 × 450 = **5,150**.

b) Sum = 9 × 1,550 + 450 × (0+1+…+8) = 13,950 + 450 × 36 = **30,150 tokens**.

c) 30,150 × $3 / 1,000,000 ≈ **$0.09**.

d) Each step adds 4,050. Total = 13,950 + 4,050 × 36 = **159,750 tokens ≈ $0.48**, more
   than 5× the cost. **The total grows quadratically with the number of steps**, and big tool
   outputs dominate. That's why we'll truncate tool output (Lesson 09), compact history
   (Module 5) and keep history cache-friendly.
</details>

<details><summary>Exercise 2 answer</summary>

```python
# 7. How much of the model is on the GPU?
for m in httpx.get(f"{OLLAMA}/api/ps", timeout=5).json()["models"]:
    gpu = 100 * m["size_vram"] / m["size"]
    ok(f"{m['name']} loaded: {gpu:.0f}% on GPU, {m['size'] / 1e9:.1f} GB total")
```
</details>

---

### Glossary
- **Tokenizer**: converts text to token IDs and back.
- **Chat template**: per-model recipe for flattening messages (and tools) into one string with special tokens.
- **Special tokens**: reserved markers like `<|im_start|>` that delimit turns.
- **KV cache**: GPU memory holding the computed state for each context token. It's what makes `num_ctx` expensive.
- **Quantization**: storing model weights with fewer bits (e.g. 4 instead of 16) to save memory.
- **Sampling**: choosing the next token from the model's probabilities.
- **Thinking / reasoning tokens**: output a model writes to "think" before its final answer.

**Next → Lesson 02: Talking to the raw API.** We write our first script that calls the
model over HTTP: request and response, then streaming tokens as they're generated.
