# Undo and rewind

The agent changed five files and you don't like the result. Two commands put things back:

| Command | What it does |
|---|---|
| `/undo` | put back the files the **last request** changed |
| `/rewind` | list this chat's requests, numbered |
| `/rewind N` | go back to **before request N**: its files *and* every later request's files are put back, and the conversation forgets them too |

```text
> /rewind
  1  Fix the subtotal bug in project/shop/cart.py
       project/shop/cart.py (+1 -1)
  2  Add a test that adding quantity 0 raises ValueError
       project/tests/test_cart.py (+7 -0)
  3  Now rename Cart to Basket everywhere
       project/shop/cart.py (+4 -4), project/tests/test_cart.py (+3 -3) and 2 more; ran 1 command that may have changed files

> /rewind 3
rewound to before request 3: "Now rename Cart to Basket everywhere"
put back: project/shop/cart.py, project/tests/test_cart.py, project/shop/__init__.py, project/README.md
not undone: 1 shell command(s) ran in these requests and may have changed files (sed -i s/Cart/Basket/ ...). The harness can't know which.
the conversation goes on from before that request
```

## How it works
Each time the agent is about to change a file with `edit_file` or `write_file`, the harness first **keeps a copy of the file as it is**. The copies belong to the request you had made, so "undo" means
"put back what that request changed". A file the agent created is removed again (and the folders it created, if they are empty).

The copies are in your user folder, next to your [saved chats](chats.md), not in your project, so they can't be committed by accident and a repository can't ship its own:

```text
<your user folder>/projects/<project>/history/<chat>.jsonl        what each request changed
<your user folder>/projects/<project>/history/blobs/ab/<hash>     the copies
```

A copy is kept once however many times a file is edited in one request, and the same content is stored once however many requests it is in.

## Choosing what to put back
`/rewind N` takes a word after the number:

| | Files | Conversation |
|---|---|---|
| `/rewind N` or `/rewind N both` | put back | forgets request N and everything after it |
| `/rewind N code` | put back | kept: the model is told, with your next message, that the files were put back |
| `/rewind N chat` | kept | forgets request N and after: the model is told which files still hold the later changes |

Add `show` to see what would happen without doing it (`/undo show`, `/rewind 3 show`).

Rewinding the conversation is written to the saved chat as one more entry, so a resumed chat is rewound too ([chats](chats.md)). It is not a way to make a read page safe: the chat **stays** marked as having read
untrusted content ([untrusted content](untrusted-content.md)), because forgetting a page doesn't undo what you now know the agent may have done with it. `/reset` starts clean.
If the older part of the conversation was already replaced by a summary ([context](context.md)), the conversation can't go back that far; the files still can.

## It never overwrites your own work
For every file the harness remembers **what the agent wrote**. It only puts the old content back if the file still holds exactly that. If you edited it since, or deleted it, that file is a **conflict**: it is
skipped and reported, and the others are still put back.

```text
SKIPPED project/shop/cart.py: has changed since the agent wrote it
files you changed since were left alone; add `force` to put the agent's earlier version back over them
```

`/undo force` (or `/rewind N force`) puts the earlier version back over yours, and **keeps your version** first: the report names its copy (a hash under `history/blobs/`), so a forced undo can itself be reversed by hand.

## What it can't undo
- **Anything a command changed.** `run_shell` can do anything, and the harness can't tell which files. A request that ran a command that may have changed files says so when you list it and when you undo it. For work that runs
  commands, keep the project in git: it is the right tool for that.
- Files changed by you, another program, or a tool you added.
- Files outside the workspace's folders: the agent can't reach them anyway.

## Limits, retention, settings
- A file bigger than 2 MB is not copied (the edit tools won't edit one that big anyway), and the copies of one project stop at 400 MB. When a copy can't be kept the edit **still happens**, and you are told once, in a warning, that
  that change can't be undone.
- The history of a chat is removed with the chat (`chat_retention_days`, [chats](chats.md)), and copies nothing refers to are removed with it.
- With `--no-save` the history lives in a temporary folder and is deleted when the session ends: `/undo` works during it.
- `"file_history": false` turns it off. A project's settings can't set it: a cloned repository shouldn't be able to switch your undo off.

## It is your command, not the agent's
The model has **no tool** that undoes or rewinds, and the history is outside the folders its tools can reach, so a web page the agent read can't ask for a rewind or tamper with what is kept. Undo is not a tool call, so
[hooks](hooks.md) and permission rules don't see it; the [path rules](permissions.md) still apply to every file it writes.

## What it measured
**Does it put things back exactly?** 300 random chats (text, CRLF, unicode, binary and empty files; several requests each, writing to existing files and to new files in new nested folders), rewound to a random request, compared with a copy of the
whole tree taken before it: **300 of 300 identical**, and 300 of 300 with a user edit in the way (the user's edit was never overwritten). The first run was 248 of 300: empty folders were left behind when two requests wrote into the same new folder. That
is fixed and tested. Run it yourself: `python scripts/history_lab.py roundtrip`.

**What it costs.** Keeping a copy took 6 to 20 ms and undoing a file 35 to 57 ms (files of 1 KB to 1 MB, on Windows). A file edited 30 times in one request keeps **one** copy (109 KB); the same file edited once in each of 30 requests keeps 30 (3.2 MB).

**Does the model know?** After an undo, the conversation still says the agent made the edit. Six runs on a small local model, each asked "quote the line as it is in the file right now" after the undo:

| | said the undone edit was still there | quoted the restored line |
|---|---|---|
| the harness says nothing | **6 of 6** | 0 of 6 |
| the harness adds a note to your next message | 0 of 6 | **6 of 6** |

Without the note the model confidently quoted code that no longer existed. That is why `/undo` and `/rewind N code` tell the model.
