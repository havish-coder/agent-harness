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

The token line shows what this turn cost: input tokens are everything sent to the model
(the whole conversation, every step), output tokens are what it wrote.

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

`--yes` skips every question. Use it only in a folder you can afford to lose.

## Cancel
Press **Ctrl+C** while the agent is working. The turn is discarded as if you never asked, and
you can continue the conversation normally.

## Commands
| Command | Does |
|---|---|
| `/reset` | forget the conversation and start fresh |
| `/bye` | quit (Ctrl+D or Ctrl+C at the prompt also quit) |
