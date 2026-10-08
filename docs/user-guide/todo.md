# The todo list

Ask a small model for a job with several parts, such as "fix the bug, add a test, update the README, write a changelog line", and it will often do the first two, say *"Done!"* and stop. Agent Harness gives the agent
a checklist to keep, and sends it back to work when it tries to finish with items still open.

```text
> Fix the subtotal bug, add a test for quantity 0, update the README and add a changelog line

● todo_write(todos=[...])
  └ Todo list updated (0 of 4 done):
    [~] 1. Fix the subtotal bug in cart.py
    [ ] 2. Add a test that quantity 0 raises ValueError
    [ ] 3. Add a Usage section to the README
    [ ] 4. Add a changelog line
● read_file(path='project/shop/cart.py')
  ...
```

## If you number your request, the harness writes the list
A small model rarely writes a todo list on its own (see what it measured). So when your request has **three or more numbered lines** ("1. fix the bug 2. add a test 3. update the README"), the harness makes them the list itself, with the first item in progress, and tells the agent in a note
added to your request. Everything else below then works as if the agent had written it. A request with fewer than three numbered lines, an indented block of numbers (code), or a list already in progress is left alone.

## What the agent does
- For a task with three or more steps it calls **`todo_write`** with the whole list: each item has a short `content` and a `status` of `pending`, `in_progress` or `completed`.
- It marks **one** item `in_progress` while it works on it, and `completed` as soon as it is done. It sends the whole list again each time (a replace, not "add an item"), so the latest call is always the state.
- For a question, or a one-step job, it doesn't use it.

The tool changes nothing on your computer, so it **never asks** for approval, in any mode.

## When it tries to finish early
If the model gives its final answer while items are still `pending` or `in_progress`, the harness adds a short note from itself ("your todo list still has unfinished items: ...") and the model carries on. It does this **at most twice per request**:
a model that decides some items aren't needed can remove them (or mark them done) and finish. It never does it
- after you refused a tool call in that request (you said no; nobody should push on),
- when the answer was cut off by the output limit, or the request stopped for another reason.

The terminal shows `↺ the todo list still has unfinished items: asking the agent to carry on`.

## Commands
| | |
|---|---|
| `/todo` | show the list: how many are done, and each item |
| `/todo clear` | empty it |

A list whose items are all completed disappears when you send your next request. `/reset` starts a new chat without one.

## Resuming, rewinding, summarising
- The list is **rebuilt from the conversation**: it is whatever the last `todo_write` call still in the chat said. A resumed or forked chat has its list back, and `/rewind` takes it back to what it was at that point ([chats](chats.md), [undo](undo.md)).
- When the conversation is summarised ([context](context.md)), the list is repeated in the summary word for word, so the summary can't lose or reword it.

## Whose words
The items are written by the model, possibly **after it read a web page or a file from a stranger**. A list written then is marked, and when the harness quotes it back to the model (in a nudge, or in a summary) it is fenced as information, not as your instructions,
the way [saved notes](auto-memory.md) are. `/todo` says so. Whatever the model then does still goes through the usual [permission rules](permissions.md): a list can't approve anything.

## What it measured
With `qwen3:4b-instruct` and a request with six numbered parts (`scripts/todo_lab.py`, 5 runs per row):

| variant | what the agent had | parts done (of 6, mean) | all six | `todo_write` calls (mean) | nudges (mean) | tool calls (mean) |
|---|---|---|---|---|---|---|
| `none` | no todo tool | 5.0 | 1/5 | (no tool) | 0 | 13.2 |
| `tool` | `todo_write`, described only by its own description | 4.0 | 0/5 | 0.0 | 0 | 12.6 |
| `rule` | the tool, and a sentence in the system prompt saying when to use it | 5.2 | 2/5 | 0.2 | 0 | 12.2 |
| `nudge` | the tool, the sentence, and the harness's check at the end | 5.0 | 2/5 | 0.0 | 0 | 10.8 |
| `seed` | all of that, and the harness writes the list from the numbered request | **5.6** | **4/5** | 0.4 | 1.8 | 4.6* |

\* calls still in the conversation at the end; the long `seed` runs had their older messages summarised (Lesson 39), so this undercounts them.

Left to itself this small model almost never wrote a todo list (0 or 1 run of 5, with or without the sentence in the prompt), so the list couldn't help it. When the harness made the list from your numbered request, **4 of 5 runs did all six parts**, and the nudge (which fired about twice a run) is part of why. So: **number the parts of a request** when there are several.

## Setting
`"todo": false` removes the tool and the nudging. A project may set it.
