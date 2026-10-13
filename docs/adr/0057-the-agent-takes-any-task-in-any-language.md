# 0057. The agent takes any task in any language: the role says so first, and the prompt's last line hands over to the request

- **Status:** Accepted
- **Date:** 2026-10-13

## Context
Asked for a C++ trie, the agent answered that the request was unrelated to the current project's files, goals or context, and that the
project was about fixing tests in a Python shop. That came from the sample folder's [progress journal](../user-guide/journal.md), left by
earlier chats. Its Goal ("Fix failing tests in the project ...") was in the system prompt, the workspace listing showed only Python files,
and nothing in the prompt said the agent could take on new work. A small model reads "the project's goal" as the limit of its job.

`scripts/generic_lab.py` measures it: six requests that have nothing to do with the sample project (a C++ trie in `trie.cpp`, C++ BFS in
the answer, a Rust function in `words.rs`, a bash script, a JavaScript debounce, a short essay in `essay.txt`). Each runs in a fresh copy
with that journal present and approvals off (bypass), so only the model's choice is measured. *Refused* is an answer that says it can't or
won't; *done* is the file existing afterwards (or code in the answer). `qwen3:4b-instruct`, 3 runs each.

## Options
1. **Leave the journal out** unless the user asks to continue. That loses what the journal is for: a new chat that knows where the last
   one stopped.
2. **Word the journal as background**, not as a goal.
3. **Say in the role** that any language and any new task is in scope.
4. **End the prompt with the hand-over**: the last thing the model reads before the request says the request is the task.

## Decision
Options 2, 3 and 4 together. Each was measured alone first:

| wording (the C++ and Rust requests, 9 runs) | refused | done |
|---|---|---|
| v0.8.0 | 9/9 | 0/9 |
| a fourth role line ("You can write code in any programming language and create new files ...") and the journal as background | 9/9 | 0/9 |
| the journal "only if the user asks to continue" | 8/9 | 0/9 |
| that, and the hand-over line at the end | 2/9 | 6/9 |
| the role rewritten to open with it | 5/9 | 4/9 |
| **the rewritten role and the hand-over line** | **0/9** | **8/9** |

What changed, in `harness/session.py` and the two section headers:

- **The role opens with what the agent is for**: "You are a coding agent for any task in any programming language (C++, Rust, JavaScript,
  Python, shell ...): write new code and new files, fix, explain, run commands. The workspace is where you work, not a limit on what you
  may do: a request doesn't have to be about the files already here, and a file that doesn't exist yet is one to create." The rest of the
  role is as before. The last clause answered the Rust refusals: "words.rs doesn't exist in the workspace".
- **The prompt ends with the hand-over** (`LAST_WORD`, a section after the workspace listing): "The user's next message is your task. It
  can be about anything, in any language: do it." `SYSTEM_PROMPT`, the one-string version that scripts and recordings use, ends with it
  too.
- **The journal is background**: its header now says "Background on earlier work: the user's request comes first, and if it is about
  something else, do that." The project memory header adds "including requests that have nothing to do with these notes".

All six requests, before and after (the one not done: a bash run that said it would write the script, then stopped):

| | refused | done |
|---|---|---|
| v0.8.0 | 9/18 (all 9 C++ and Rust) | 7/18 |
| now | **0/18** | **17/18** |

## Consequences
- The role is 70 tokens longer (73 to 143), and the hand-over line costs 19: 1% of an 8K window. The prompt's tests
  set a 3,000-token window where they had 1,500, because the listing then got dropped instead of shrunk.
- The replay cassette was recorded again (the system prompt is part of what it checks).
- A request about the journal's subject still benefits from it: the journal is background, not gone.
- These are wordings measured on one 4B model. A different model can need different words, and the lab is there to check.
