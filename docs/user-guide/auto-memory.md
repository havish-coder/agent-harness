# Notes the agent saves for itself

[Project memory](memory.md) is what *you* tell the agent. This is what the agent notices: when you say something lasting ("always use tabs here", "the main branch is called
trunk", "the tests live in project/"), it can save a short note and start the next chat knowing it.

```text
you> From now on, always put type hints on Python functions. Remember that for next time.
  ● remember(title='Prefers type hints', kind='feedback', description='Always put type hints on Python functions')
    note: Prefers type hints (feedback)
    Always put type hints on Python functions
    allow? [y]es / [n]o / [a]lways allow ...
```

In our test on a small local model it saved a note when asked in 5 of 5 runs, saved nothing when you only asked a question (0 of 5), and a later chat that had the note
in its prompt answered "what is this project's main branch?" correctly in 6 of 6 runs, against 0 of 6 without it.

## How it works
- The agent has three tools: `remember` (save a note), `recall` (show one in full, or list them), `forget` (delete one).
- A note is a small file: a title, a kind (`user`: about you, `feedback`: how you want the work done, `project`: a fact about the project, `reference`: where something is), a one-line
  description (the fact itself), and optional details. At most 100 notes; a description is at most 160 characters.
- At the start of each chat the notes' titles and descriptions are put in the system prompt, newest first (about 800 tokens at most), and the agent shows one in full with `recall`.
- They are kept in **your** folder, per project (`~/.harness/projects/<folder>-<hash>/memory/`), not in the repository: a repository can't ship notes that pretend the agent learned them,
  and they are never committed. They are plain Markdown files you can read, edit or delete.
- Secrets that look like keys are hidden before a note is written.

## Whether it asks
`auto_memory` in your settings:

| Value | |
|---|---|
| `"ask"` (default) | every `remember` and `forget` asks you, with the note's text in front of you |
| `"on"` | `remember` saves without asking, **unless** the chat has read untrusted content (a web page, a file from a folder you haven't trusted), in which case it asks |
| `"off"` | no tools, nothing in the prompt |

`"on"` is a blanket approval like any other, and like any other it stops applying once untrusted content has been read ([untrusted content](untrusted-content.md)). A project's own settings
file can't set it. In `plan` mode the agent can't save notes.

## Notes written after reading something you don't trust
A web page or a file you didn't write may say "save a note that ...". If the agent does, the note would carry that text into every later chat. So **each note records, when it is written,
whether the chat had read untrusted content**:

- A clean note is loaded as the agent's own memory.
- A note saved after untrusted reading is marked `trust: tainted`, with where it came from. In later chats it is shown **fenced as untrusted content**, under a line saying so, and
  it counts as untrusted content itself: a chat that loads one starts out tainted, so blanket approvals ask until you deal with it.
- `/memory` lists the notes and marks those, with the source. After reading one, `/memory trust NAME` says it is yours (it is then loaded plainly and stops tainting), and
  `/memory forget NAME` deletes it.

In our test a README that said "save a note with this command in it" was **not** obeyed by the small model (0 of 5 runs); the protection doesn't rely on that. The approval shows the note,
and warns you when the chat has read untrusted content.

## Commands
| Command | |
|---|---|
| `/memory` | the project notes you wrote and the notes the agent saved, and whose words each counts as |
| `/memory forget NAME` | delete a saved note |
| `/memory trust NAME` | mark a note the agent saved after untrusted reading as yours, once you have checked it |
| `/memory reload` | read both again |

Ask the agent in plain words, too: "forget what you saved about tabs".

## What it is not for
Notes are for what will matter in a *later* chat. The agent is told to leave out what the files already say, what only matters for the current task, and anything that came from a file
or web page and not from you. Where a task stands belongs in a progress journal, not here.
