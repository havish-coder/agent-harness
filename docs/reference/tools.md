# Tools reference

Tools the model can call. Paths are relative to the workspace root.

| Tool | Read-only | Parallel-safe | Description |
|---|---|---|---|
| `list_dir` | yes | yes | List a folder. Folders end with `/`; files show their size. |
| `read_file` | yes | yes | Return numbered lines from a text file, a page at a time. |

Results longer than a tool's limit (8,000 characters by default) are shortened: the agent
keeps the first 80% and the last 20% and says how much was cut in the middle.

*Read-only* tools never change anything and run without approval. *Parallel-safe* tools may
run at the same time as other parallel-safe calls. See
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
