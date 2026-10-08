# Tools reference

Tools the model can call. Paths are relative to the workspace root.

| Tool | Read-only | Parallel-safe | Clearable | Description |
|---|---|---|---|---|
| `list_dir` | yes | yes | yes | List a folder. Folders end with `/`; files show their size. |
| `read_file` | yes | yes | yes | Return numbered lines from a text file, a page at a time. |
| `glob` | yes | yes | yes | Find files by name pattern, newest first. |
| `grep` | yes | yes | yes | Search inside files with a regular expression. |
| `edit_file` | no | no | no | Replace exact text in a file the model has read. A copy of the file is kept first ([undo](../user-guide/undo.md)). |
| `write_file` | no | no | no | Create a file, or replace a whole file the model has read. A copy of an existing file is kept first ([undo](../user-guide/undo.md)). |
| `run_shell` | no | no | yes | Run a shell command; returns the exit code and output, or with `background` starts it and returns an id ([background tasks](../user-guide/background-tasks.md)). |
| `web_fetch` | no | yes | yes | Fetch one web page and return its text. |
| `remember` | no | no | no | Save a note for later chats in this project (unless `auto_memory` is `off`). |
| `recall` | yes | yes | yes | Show a saved note, or list them. |
| `forget` | no | no | no | Delete a saved note. |
| `delegate` | yes | no | no | Give a job to a sub-agent and get back its report (unless `subagents` is `false`). Read-only for permissions: what the sub-agent does is decided as the parent's calls are ([sub-agents](../user-guide/sub-agents.md)). |
| `task_output` | yes | yes | yes | The end of a background task's output, and whether it is still running; `wait` waits for it to end. Deferrable. |
| `task_stop` | no | no | no | Stop a background task and what it started. Deferrable. |
| `use_skill` | yes | yes | yes | Load a skill's text or one of its files; offered only while there is a skill to load ([skills](../user-guide/skills.md)). |
| `tool_search` | yes | no | no | Find tools whose definitions are held back, and load them; offered only while some are held back ([tool search](../user-guide/tool-search.md)). |
| `todo_write` | yes | no | no | Replace the agent's todo list (unless `todo` is `false`). Changes nothing outside the harness, so it never asks. |
| `ask_user` | yes | no | no | Ask the user a question, with up to four choices; offered only where the interface can ask. |
| `exit_plan_mode` | yes | no | no | Show the user a plan to approve; offered **only in plan mode**. Only the user's answer changes the mode. |
| `update_progress` | no | no | no | Write one section of the project's progress journal (unless `journal` is `off`). |

Results longer than a tool's limit (8,000 characters by default) are shortened: the agent
keeps the first 80% and the last 20% and says how much was cut in the middle.

*Read-only* tools never change anything and run without approval. *Parallel-safe* tools may
run at the same time as other parallel-safe calls. *Clearable* tools return something the model can get again by calling
the tool again, so when the window fills their old results may be replaced by a short note
([details](../user-guide/context.md#when-the-window-fills-clearing-old-results)). See
[Writing a tool](../developer-guide/writing-tools.md#safety-flags) for what the flags mean.

## `list_dir`
| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | no | `.` | Folder to list. |

Result: one entry per line, folders first, e.g. `recipes/` or `notes.txt  (120 bytes)`.
An empty folder returns `(empty folder)`. A file or a missing folder returns an error with a
hint (`use read_file`, `Did you mean: ...?`).

## `read_file`
| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | | File to read. |
| `offset` | integer | no | `1` | First line. `0` is treated as `1`; negative counts from the end (`-1` = last line). |
| `limit` | integer | no | `300` | Maximum lines to return. |

Result: a header line, then numbered lines (`cat -n` style, number and a tab):
```text
big.log: lines 1500-1501 of 3000. More below: read_file(path='big.log', offset=1502)
  1500	01500 INFO request handled in 45 ms
  1501	01501 INFO request handled in 46 ms
```

Limits: at most `limit` lines and about 7,000 characters per call (the header says where to
continue); lines longer than 500 characters are cut with a marker.

| Situation | Result |
|---|---|
| empty file | `(notes.txt is empty)` |
| offset past the end | `(offset 10 is past the end: notes.txt has 3 lines; ...)` |
| same lines read again, file unchanged | a short note pointing to the earlier result |
| not valid UTF-8 | content with bad bytes shown as `�`, and a note in the header |
| binary file (NUL byte in the first 8 KB) | error |
| folder | error suggesting `list_dir` |
| missing file | error with up to three similar names (`Did you mean: notes.txt?`) |

## `glob`
| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `pattern` | string | yes | | Glob pattern. Without `/` it matches file names in every folder (`*.py`); with `/` it matches the relative path (`src/**/test_*.py`; `**` may match zero folders). |
| `path` | string | no | `.` | Folder to search. |

Result: matching file paths, most recently modified first, at most 100 (then
`... and N more`). Folders such as `.git`, `.venv` and `node_modules` are skipped.

## `grep`
| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `pattern` | string | yes | | Python regular expression. An invalid one is searched as plain text, with a note. |
| `path` | string | no | `.` | File or folder to search. |
| `glob` | string | no | | Only files matching this pattern (same rules as `glob`). |
| `ignore_case` | boolean | no | `false` | Case-insensitive matching. |
| `output` | `"lines"` / `"files"` / `"count"` | no | `"lines"` | Matching lines, file names, or matches per file. |
| `context` | integer | no | `0` | Lines before and after each match (`lines` mode). |
| `limit` | integer | no | `50` | Maximum lines (or files) returned. |

Result (`lines`): `path:line: text` for matches, `path-line- text` for context lines, `--`
between groups, then a summary such as `(2 matches in 2 files)`. Binary files, files over
2 MB and ignored folders are skipped. Lines longer than 300 characters are cut.

## `edit_file`
| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | | File to edit. |
| `old_string` | string | yes | | Exact text to replace (spaces and indentation included). |
| `new_string` | string | yes | | Replacement text. |
| `replace_all` | boolean | no | `false` | Replace every occurrence instead of exactly one. |

Checked **before** you are asked to approve (a failing check returns an error to the model):

| Check | Error tells the model |
|---|---|
| the file was read in this conversation | to read it first |
| it hasn't changed since (modification time, then content hash) | to read it again |
| `old_string` differs from `new_string` and isn't empty | there is nothing to change / what to copy |
| `old_string` occurs exactly once (unless `replace_all`) | the line numbers of every occurrence, to add context |
| `old_string` occurs at all | the most similar line in the file |
| UTF-8 text, under 1 MB | it can't be edited safely |

Forgiving matches: if the file uses Windows line endings (CRLF) and `old_string` uses plain
newlines, both strings are converted; if `old_string` includes `read_file`'s line-number
prefixes and only matches without them, they are removed. Otherwise the file's bytes,
including its line endings, are preserved exactly.

Result: `Edited <path>: N replacement(s).` followed by a unified diff (2 lines of context, at
most 60 lines). The approval prompt shows the same diff.

## `write_file`
| Argument | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | File to create or overwrite. Missing folders are created. |
| `content` | string | yes | The complete new contents. |

Creating a file needs no prior read. Overwriting an existing file requires that it was read
and hasn't changed since, and is marked **destructive** in the approval prompt. Result:
`Created <path> (N lines).` or `Overwrote <path> (N lines, was M).` plus a diff.

## `run_shell`
| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `command` | string | yes | | The command, run in the workspace root (use `cd folder && ...` for another folder). |
| `timeout` | integer | no | `60` (`1800` in the background) | Seconds before the command is stopped; at most 600 (`7200` in the background). |
| `background` | boolean | no | `false` | Start the command and return at once with a task id (`bg-1`); you are told when it ends. Not in the schema when `background_tasks` is `false`. |

The shell is **bash** wherever possible: on Windows, Git for Windows' bash when installed,
otherwise PowerShell 7, otherwise Windows PowerShell 5.1 (where `&&` doesn't work; use `;`).
Set `HARNESS_SHELL` to `bash`, `pwsh` or `powershell` to choose. The tool description tells the
model which shell it has ([ADR 0011](../adr/0011-prefer-bash-no-cwd.md)).

Behaviour:
- Standard input is closed: commands that wait for input fail immediately instead of hanging.
- On timeout the command **and every process it started** are stopped.
- Output is UTF-8 (including on Windows); Python programs run with `PYTHONUTF8=1`.
- The Python running the agent is first on `PATH`, so `python` means that interpreter.
- PowerShell's exit code is the real one of the last command (PowerShell itself only reports 0 or 1).
- The command inherits your environment variables **except secrets**: any variable whose name
  contains a word like `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `AUTH` or `COOKIE`, or whose value looks
  like an API key (`sk-...`), is removed. Allow specific ones with the `shell_env_keep`
  [setting](configuration.md). See [Permissions](../user-guide/permissions.md#how-commands-are-read).

Result: a status line (`exit code 0 (success) · 1.2 s · in .`, or `TIMED OUT after 60 s`),
then `--- stdout ---` and `--- stderr ---` sections, or `(no output)`. Long output keeps the
first 30% and the last 70% of about 7,000 characters, because summaries (test results,
errors) are usually at the end.

## `web_fetch`
Available unless `web_fetch` is `false` in the [settings](configuration.md). Not read-only: the first fetch from
a site asks ([Reading web pages](../user-guide/web.md)).

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `url` | string | yes | | The full address, `http://` or `https://`. |
| `max_chars` | integer | no | `8000` | Characters of the page to return; at most 30,000. |

Result: a header (`HTTP 200 · text/html · https://example.com/page`, the title, and `redirected from ...` when
it followed redirects within the site), a blank line, then the page as text: scripts and styles removed, a blank
line between paragraphs, `- ` before list items, links as `text (url)`. Long pages end with how many characters
were cut. Images, archives and other non-text types return `Not shown: this is a ... file, not text.`

Limits: public servers only (ports 80 and 443; not this computer, private networks, cloud metadata addresses,
`file://` and other schemes; `user@host` addresses are refused), 15 seconds, about 2 MB read (counted after
decompression), up to 5 redirects within the same site. A redirect to a different site isn't followed: the result
names the new address. Proxy environment variables are ignored. The result is
[untrusted content](../user-guide/untrusted-content.md): fenced, and it taints the chat.
