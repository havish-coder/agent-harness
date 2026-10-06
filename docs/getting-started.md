# Getting started

This tutorial takes you from nothing to an agent answering questions about files on your
computer. It takes about 15 minutes, most of it downloading the model.

## 1. Install the model server
1. Install [Ollama](https://ollama.com/download) and start it (it runs in the background).
2. Download the default model, about 2.5 GB:
   ```bash
   ollama pull qwen3:4b-instruct
   ```
3. Check it answers:
   ```bash
   ollama run qwen3:4b-instruct "Say hello in five words."
   ```

Any GPU with 4 GB of memory runs it at roughly 20 tokens per second; on a CPU it is slower
but works.

## 2. Install Agent Harness
```bash
git clone https://github.com/havish-coder/agent-harness.git
cd agent-harness
python -m venv .venv
.venv\Scripts\activate             # macOS/Linux: source .venv/bin/activate
pip install -e ".[tui,dev]"
python scripts/check_setup.py      # checks Python, Ollama and the model
```

## 3. Your first conversation
The repository ships a small sample folder, `workspace/`, with notes, a recipe, a CSV file
and `project/`, a tiny Python library with a bug to find. Start the agent there:

```bash
harness --workspace workspace
```

Try:
```text
you> How many TODOs are in my notes?
  → read_file(path='notes.txt')
    TODO: buy milk ...
agent> There are 3 TODOs in your notes.
  [726 input + 32 output tokens]
```

The lines starting with `→` are **tool calls**: the model asked the harness to run
`read_file`, the harness ran it and sent the result back, and the model answered from it.

## 4. Let it fix a bug
`workspace/project/` has a bug: the cart's subtotal ignores quantities. Ask:

```text
you> The cart subtotal in project/shop/cart.py ignores the quantity. Fix it.
     Then run the project's tests with run_shell to check.
```

The agent finds and reads the file, then proposes an edit. **Nothing changes until you
approve**, and you see exactly what would change:

```text
  ? edit_file wants to run
    --- a/project/shop/cart.py
    +++ b/project/shop/cart.py
    -        return sum(price for _, price, qty in self.items)
    +        return sum(price * qty for _, price, qty in self.items)
    allow? [y]es / [n]o / [a]lways for edit_file: y
```

Running the tests asks for approval too. Afterwards, undo the change with
`git checkout workspace/project`.

## 5. Point it at your own folder
```bash
harness --workspace C:\path\to\a\project
```

> **Safety:** in this version paths aren't confined to the workspace yet. Use a folder you
> don't mind the agent reading. See [SECURITY.md](../SECURITY.md).

## Next steps
- [User guide](user-guide/README.md): everything the terminal app can do.
- [Architecture](architecture.md): what happens between your question and the answer.
