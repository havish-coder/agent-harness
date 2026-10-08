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
    allow? [y]es / [n]o: y
```

Running the tests asks for approval too. Afterwards, `/undo` puts the file back (or
`git checkout workspace/project`).

In a folder you have trusted (`/trust`), the question also offers `[a]lways`, to stop asking for that tool in this
session. In a folder you haven't, it doesn't once the agent has read something there: see
[untrusted content](user-guide/untrusted-content.md).

## 5. Point it at your own folder
```bash
harness --workspace C:\path\to\a\project
```

> **Safety:** the file tools only reach the workspace folder (and folders you add), and anything that
> changes something asks you first, showing the diff or the command. Commands you approve run with your
> rights, so read them. If the project is yours, `/trust` it. See [SECURITY.md](../SECURITY.md).

## 6. Or use it in your browser
```bash
harness --web --workspace workspace
```

The same agent opens as a page in your browser: type requests at the bottom right, watch the answer stream in the middle,
the run graph grow beside it and commands print below, and answer approvals with **Yes** or **No** under the diff. The
server listens on this computer only and needs the key in the address it prints; Ctrl+C in its terminal stops it. See
[the web UI](user-guide/web-ui.md).

## Next steps
- [User guide](user-guide/README.md): everything the terminal app and the web UI can do.
- [Architecture](architecture.md): what happens between your question and the answer.
