# Using the terminal app

## Start
```bash
harness                                   # model qwen3:4b-instruct, workspace ./workspace
harness --workspace C:\path\to\project    # another folder
harness --model qwen3:4b                  # another Ollama model
```
All flags: [CLI reference](../reference/cli.md).

## Ask
Type a request and press Enter. While the agent works you see each tool call and a preview
of its result:

```text
you> what's in the recipes folder?
  → list_dir(path='recipes/')
    pancakes.md  (163 bytes)
agent> The recipes folder contains one file: `pancakes.md` (163 bytes).
  [699 input + 49 output tokens]
```

The line in brackets shows what this turn cost: input tokens are everything sent to the model
(the whole conversation, every step), output tokens are what it wrote, and *cached* is the part
of the input the model server reused from the previous request instead of processing it again.
The price is `free` for models on your computer, a dollar amount for models with a known
price, and `price unknown` otherwise (add prices in [settings](configuration.md)).

## Approve or deny actions
Tools that only look at things (listing, reading, searching) run straight away. Any tool that
can **change** something asks first:

```text
  → append_note(text='call the dentist')
  ? append_note wants to run
    allow? [y]es / [n]o / [a]lways for append_note: y
```

| Answer | Effect |
|---|---|
| `y` | run this call |
| `n` or Enter | don't run it; the model is told you declined and asked to check with you |
| `a` | run it, and allow this tool without asking for the rest of the session |

For file edits the prompt shows exactly what will change, as a diff:

```text
  ? edit_file wants to run
    --- a/project/shop/cart.py
    +++ b/project/shop/cart.py
    @@ -13,5 +13,5 @@

         def subtotal(self) -> float:
    -        return sum(price for _, price, qty in self.items)
    +        return sum(price * qty for _, price, qty in self.items)
    allow? [y]es / [n]o / [a]lways for edit_file:
```

Overwriting an existing file with `write_file` is flagged `(may destroy data)`.

`--yes` skips every question. Use it only in a folder you can afford to lose.

## Ask for verification
The agent can run commands (`run_shell`), such as your tests, but small models rarely check
their own work unless asked. **Say it in the request**:

```text
you> Add a test that adding an item with quantity 0 raises ValueError.
     Then run the tests and fix any problem in your new test.
```

In our measurements with `qwen3:4b-instruct`, the same request without the second sentence
produced a broken test 3 times out of 3; with it, the agent ran the tests, saw the error,
fixed it and re-ran them, 3 times out of 3. Putting the rule in the system prompt instead did
not help (0 of 3).

## When the model server has a problem
Temporary failures (a crashed GPU runner, an overloaded or rate-limited cloud API, a dropped
connection) are retried automatically, waiting a little longer each time:

```text
  ! HTTP 500: CUDA error — retrying in 0.6 s (retry 1)
  ! HTTP 500: CUDA error — retrying in 1.1 s (retry 2)
```

Up to 4 retries, at most 90 seconds of waiting per model call; if the server says how long to
wait (`Retry-After`), that wins. Permanent errors (a wrong API key, an unknown model) fail
immediately. With `--fallback-model`, a second model gets one try after the retries run out.

## Cancel
Answers appear as the model writes them. Press **Ctrl+C** while the agent is working, even
mid-sentence: the connection to the model is closed, so it stops generating immediately, and the turn is
discarded as if you never asked. You can continue the conversation normally.

## Commands
| Command | Does |
|---|---|
| `/reset` | forget the conversation and start fresh |
| `/cost` | tokens and cost so far in this session, per model |
| `/bye` | quit (Ctrl+D or Ctrl+C at the prompt also quit) |
