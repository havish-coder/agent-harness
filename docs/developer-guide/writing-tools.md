# Writing a tool

A tool is a Python function the model can ask the agent to run. The `@tool` decorator turns
a function into a `Tool` with a JSON Schema built from its type hints and docstring.

## A minimal tool
```python
from harness.tools.base import tool

@tool(read_only=True, concurrency_safe=True)
def word_count(path: str, unique: bool = False) -> str:
    """Count the words in a text file.

    Args:
        path: File path relative to the workspace root.
        unique: Count distinct words instead of all words.
    """
    words = open(path, encoding="utf-8").read().split()
    return str(len(set(words)) if unique else len(words))
```

The model sees:
```json
{"name": "word_count",
 "description": "Count the words in a text file.",
 "parameters": {"type": "object",
                "properties": {"path": {"type": "string", "description": "File path relative to the workspace root."},
                               "unique": {"type": "boolean", "description": "Count distinct words instead of all words.", "default": false}},
                "required": ["path"]}}
```

## Rules
- **The docstring is the model's manual.** Say *when* to use the tool, not only what it
  does. A tool without a docstring raises `TypeError` at import time.
- **Return text written for a model**: short, specific, and with a hint when something fails
  (`"No matches. Try a broader pattern."`). Exceptions are fine: the agent turns them into
  `Error: <Type>: <message>` results the model can read.
- **Supported argument types:** `str`, `int`, `float`, `bool`, `dict`, `list[X]`,
  `Literal["a", "b"]`, and `X | None`. Arguments without a default are required.

## Safety flags
Flags are **fail-closed**: leave one out and the agent assumes the risky value.

| Flag | Default | Set it to `True` when... | Effect |
|---|---|---|---|
| `read_only` | `False` | the tool never changes anything | no approval needed |
| `concurrency_safe` | `False` | the tool can run at the same time as others, **on another thread** | may run in parallel with neighbouring safe calls |
| `destructive` | `False` | the tool may delete or overwrite data | shown as a warning when approving |
| `clearable` | `False` | calling the tool again gives the model the same information back (a read, a search, a fetch) | when the window fills, an old result may be replaced by a short note |

`concurrency_safe=True` is a promise that the tool's code is thread-safe and that its result
doesn't depend on another call in the same reply. Read-only tools usually qualify; tools that
change things never should.

A flag can be a function of the call's arguments:
```python
@tool(read_only=lambda args: args["command"].split()[0] in {"ls", "cat"})
def shell(command: str) -> str: ...
```
If the function raises, the flag counts as `False`.

## Checks and previews
Two optional hooks make tools that change things safer and easier to approve:

```python
def check(path: str, text: str) -> str | None:
    # Return an error message for the model, or None if the call can run.
    ...

def preview(path: str, text: str) -> str:
    # Return what the call would do (e.g. a diff), shown in the approval prompt.
    ...

my_tool.check = check
my_tool.preview = preview
```

The agent runs `check` **before** asking for approval, so the user never approves a call
that would fail. Both receive the same (validated) arguments as the tool.

## Registering a tool
Return it from a factory and pass it to the agent:
```python
agent = Agent(provider, make_fs_tools(workspace) + [word_count], system_prompt)
```
