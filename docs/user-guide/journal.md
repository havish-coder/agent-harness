# Resume where you left off: the progress journal

A new chat starts from zero. [Saved chats](chats.md) bring a *conversation* back, and [memory](memory.md) keeps *facts*. Neither says **where the work stands**: what was decided, what's done,
what failed and shouldn't be tried again, what comes next. After a long task that is what you want when you come back tomorrow.

The progress journal is one Markdown file in your project, `.harness/progress.md`, with six sections:

```markdown
# Goal
Fix the subtotal bug in project/shop/cart.py, then add a test that quantity 0 raises ValueError.

# Done so far
- Found that subtotal() summed unit prices and ignored the quantity; changed it to price * quantity.

# Issues & approaches
- Editing before reading the file fails: read it first.

# Current state
subtotal() is fixed; the test for quantity 0 is not written yet.

# Next steps
- Add a test in project/tests/test_cart.py that adding quantity 0 raises ValueError.

# Key files
project/shop/cart.py, project/tests/test_cart.py
```

Every new chat in the project, from the terminal or (later) the browser, reads it at the start and puts it in front of the agent, and the start-up line shows where things stood:
`progress journal read to pick up from (updated ...): subtotal() is fixed; the test for quantity 0 is not written yet`. Say "continue" and the agent starts from **Current state** and **Next steps**.

## It is opt-in
Nothing is written until you say so. The first time a turn **changes something** (an edit, a new file, a command that writes), the terminal asks once:

```text
Keep a progress journal for this project, so later chats can pick up where this one stopped?
  [y] yes / [n] not now / [v] never for this project
```

- `y` starts the journal from this chat.
- `n` doesn't ask again in this chat.
- `v` writes `"journal": "off"` to `.harness/settings.local.json` (your own settings; keep that file out of git).

A turn that only read files never asks. You can also start it any time with `/progress start`.

## When it is updated
Once a project has a journal, the harness updates it:
- after a turn in which something changed,
- before the conversation is summarised to make room ([context](context.md)),
- when the chat ends (`/bye`, Ctrl+D).

An update is **one model call** (about half a minute on a small local GPU) that is shown the journal and the recent conversation and returns the whole updated file. The harness **checks the answer** before it
writes it: all six headings in order, within about 1,500 tokens, no `<untrusted>` tags, secrets hidden. A bad answer leaves the old journal in place and says so. The agent can also write one section itself,
with the `update_progress` tool, while it works.

Several chats can use the same journal at once (a terminal and a browser, say). Each update re-reads the latest file under a lock before it writes, writes atomically, and asks the model again once
if another chat changed the file in the meantime. The file's header says which chat wrote it last.

## Commands
| Command | |
|---|---|
| `/progress` | show the journal: where it is, when and by whom it was last updated, whose words it counts as |
| `/progress start` | turn it on (`"journal": "on"` in your local settings) and write the first one from this chat |
| `/progress stop` | turn it off: no more reading or updating. The file stays, `/progress start` brings it back |
| `/progress update [what to stress]` | update it now |
| `/progress clear` | delete the file |
| `/progress trust` | say a journal marked untrusted is yours, once you have read it |

`harness --fresh` starts one chat without reading the journal.

## What it measured
Two separate terminal sessions on the sample project. Session 1: "fix the subtotal bug; the next job, for the next chat, is a test that quantity 0 raises ValueError". Session 2, a new process: "Please continue." Four runs each on `qwen3:4b-instruct`, a small local model:

| | session 2 knew the next job | re-read the file | tool calls | redid the fix | wrote the test |
|---|---|---|---|---|---|
| **with the journal** | 3 of 4 | 4 of 4 | 4.8 | 0 of 4 | 1 of 4 |
| without it | 0 of 4 | 0 of 4 | 0.0 | 0 of 4 | 0 of 4 |

Without a journal, "Please continue." did **nothing** (no tool call in any run: there was nothing to continue from). With one, the new chat went to the right file, did real work and never redid the finished fix.
What it did not do reliably is carry out the next step: a small model often turns "continue" into "check the work and report". The journal gets a chat to the right place; how far it goes from there depends on the model.
In these runs even the first chat's fix was right only about half the time, which limits everything after it. Run it yourself: `python scripts/journal_lab.py`.

## Whose words is it?
The journal is written by the agent, from a conversation that may have read web pages and files from a stranger, and read by every later chat. So it follows the same rules as [saved notes](auto-memory.md):

- A journal updated after the chat had read **untrusted content** says so in its header (`trust: tainted`, with the sources). It is read back **fenced**, as information, and the chat that reads it starts tainted,
  so blanket approvals ask. A later clean chat doesn't wash it; `/progress trust` does, after you've read it.
- In a folder you haven't [trusted](untrusted-content.md), the whole file is read as information whoever wrote it: a cloned repository could ship its own `.harness/progress.md`.
- Even when it is plain, the journal is framed as a record of progress to check against the files, not as orders.
- The agent can't edit the file with `edit_file` without asking (`.harness/` is a protected folder). The `update_progress` tool needs no question once a journal exists, but like any blanket approval it asks again
  after untrusted content has been read.

## Setting
`"journal"`: `"ask"` (default: offer one when a turn changes something), `"on"` (keep one, no question), `"off"`. Not accepted from project settings.
