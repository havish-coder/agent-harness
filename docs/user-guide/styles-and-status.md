# Output styles and the status line

## Output styles
A style changes **how the agent writes**, not what it can do. It adds instructions to the
agent's system prompt.

| Style | The agent... |
|---|---|
| `default` | answers normally |
| `concise` | answers in a few sentences, without announcing or summarising its steps |
| `explanatory` | explains why each change is right, and adds short "Insight:" notes about the codebase |
| `learning` | does routine work itself but asks **you** to write small, meaningful pieces of code, then reviews them |
| `latex` | writes math in LaTeX (`$...$`, `$$...$$`), shown with Unicode symbols in the terminal ([math](math-and-export.md)) |

Switch at any time with `/style name` (the conversation is kept; the new style applies from the
next reply). `/style` alone lists them. To start with a style, set it in your settings:

```json
{ "output_style": "concise" }
```

### Your own styles
A style is a Markdown file; its text is added to the system prompt:

```markdown
---
description: replies in the team's review format
---
When you change code, end your answer with a "Changes" list (one line per file) and a
"How to test" section.
```

Save it as `review.md` in `~/.harness/styles/` (for you) or `<workspace>/.harness/styles/` (for a
project), then `/style review`. A project's styles can't replace the built-in ones.

Switching style changes the start of the conversation the model sees, so the model server can't
reuse its cache of the earlier prompt for the next call (see [costs](terminal.md#ask)). Pick a style
at the start of a session when you can.

## The status line
Under the prompt, a line shows the state of the session:

```text
qwen3:4b-instruct · context 3.2k/8.2k (39%) · free · style concise
```

| Part | Meaning |
|---|---|
| model | the model answering |
| context | how big the conversation was at the last model call; with Ollama, out of the context window |
| cost | the session so far (`free`, a dollar amount, or `price unknown`) |
| style | shown when it isn't `default` |

When the context gets close to 100%, the beginning of the conversation is about to be lost (see
[models](models.md)); start fresh with `/reset` or a new session.

### Your own status line
Set `status_line` to a command. It receives the session state as JSON on standard input and its
first line of output is shown instead:

```json
{ "status_line": "python C:/Users/you/.harness/status.py" }
```

```python
# status.py
import json, sys
s = json.load(sys.stdin)
print(f"{s['model']} | {s['turns']} turns | {s['context_tokens']} tokens")
```

The JSON has `provider`, `model`, `context_tokens`, `context_window`, `cost`, `style`,
`workspace` and `turns`. The command runs before each prompt with a 2-second limit; if it fails,
the built-in line is shown. Because it runs a program, `status_line` is only accepted from your
user or local settings, the environment or flags, **never from a project's settings**.
