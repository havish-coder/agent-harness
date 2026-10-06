# Tools reference

Tools the model can call. Paths are relative to the workspace root.

| Tool | Read-only | Parallel-safe | Description |
|---|---|---|---|
| `list_dir` | yes | yes | List a folder. Folders end with `/`; files show their size. |
| `read_file` | yes | yes | Return a text file's full contents (UTF-8). |

*Read-only* tools never change anything and run without approval. *Parallel-safe* tools may
run at the same time as other parallel-safe calls. See
[Writing a tool](../developer-guide/writing-tools.md#safety-flags) for what the flags mean.

## `list_dir`
| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | no | `.` | Folder to list. |

Result: one entry per line, folders first, e.g. `recipes/` or `notes.txt  (120 bytes)`.
An empty folder returns `(empty folder)`.

## `read_file`
| Argument | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | File to read. |

Result: the file's text. Errors (missing file, not UTF-8) are returned as
`Error: <Type>: <message>`.
