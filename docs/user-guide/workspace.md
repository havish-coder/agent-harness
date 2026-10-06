# The workspace and its boundary

The **workspace** is the folder you start the agent in (`harness --workspace <folder>`, or the
current folder). Every file tool (`read_file`, `list_dir`, `glob`, `grep`, `edit_file`,
`write_file`) works only inside it. Paths are relative to its root: `src/app.py`, not
`C:\projects\app\src\app.py`, although absolute paths that point inside the workspace work too.

## What is refused
A path is checked by where it **really leads**, not by how it is written. The agent can't use:

| Path | Why it's refused |
|---|---|
| `../other-project/notes.txt` | leads out of the workspace |
| `C:/Users/you/Documents/taxes.pdf`, `/etc/passwd` | an absolute path outside it |
| `link/secret.txt`, where `link` is a symlink or Windows junction to another folder | the link leads out |
| `notes.txt:hidden` | `:` in a name opens a hidden NTFS data stream on Windows |
| `app.py.`, `app.py ` | Windows silently drops trailing dots and spaces, so the name means another file |
| `NUL`, `con.txt`, `COM1.log` | Windows device names, not files |

The model gets an error it can act on, for example:

```text
Error: OutsideWorkspace: '../other-project/notes.txt' is outside the workspace. Tools can only
use files inside it; paths are relative to the workspace root.
```

Links inside the workspace that lead out of it are **shown but never entered**: `list_dir` and the
file overview in the system prompt name them as `link  (link outside the workspace)`, and `glob`
and `grep` skip them. `@mentions` of files outside the workspace aren't attached.

## Allowing more folders
If the agent should also use another folder, for example a shared library next to your project,
add it to your **user or local** settings:

```json
{ "additional_directories": ["../shared-lib", "D:/datasets/sales"] }
```

Relative folders are relative to the workspace. The setting can also come from the environment
(`HARNESS_ADDITIONAL_DIRECTORIES`, folders separated by `;` on Windows and `:` elsewhere) or flags,
but **not from a project's `.harness/settings.json`**: a repository you clone must not be able to
give the agent access to your other folders.

## What the boundary doesn't cover
The boundary applies to the file tools. **`run_shell` commands run with your full rights**: a
command can read or change any file you can. Approval is what protects you there (read each command
before approving it); v0.5 adds command analysis and permission rules. See the
[security model](../security.md) for the full picture.
