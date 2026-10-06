# 0025. Confine file tools by resolving paths, then checking containment

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Until v0.4, `Workspace.path()` only joined a model-supplied path to the workspace root. A path
like `../secret.txt`, an absolute path, or a link inside the workspace pointing out of it reached
any file the user can read or write (measured in the attack lab, `tests/security/`). All file
tools already go through `Workspace.path()`, so one function can enforce the boundary.

On Windows the same file has many spellings: forward or back slashes, any letter case, drive
letters, `\\?\` and UNC (`\\localhost\C$\...`) prefixes, junctions, and names the file system
rewrites (trailing dots and spaces dropped, `name:stream` opening an alternate data stream,
`NUL` opening a device).

## Options
1. **String checks** on the path as written (reject `..`, reject absolute paths). Every new
   spelling is a new bypass; links aren't visible in the string at all.
2. **Resolve, then check containment**: let the OS-aware `Path.resolve()` turn the path into its
   one real location (applying `..`, following symlinks and junctions), then require that
   location to be the root or inside it, comparing paths as the platform does (case-insensitive
   on Windows), never by string prefix.
3. **An OS sandbox** for the whole process. Strong, but not portable, and not available
   without extra software on Windows.

## Decision
Option 2, plus a short list of names refused before resolving because the file system doesn't
treat them as plain names (`:` outside a drive letter, trailing dot or space, Windows device
names). Those are refused on every OS so behaviour doesn't depend on the platform. Folder walks
(`glob`, `grep`, `list_dir`, the workspace overview) don't enter links that lead out, and say so.
Extra folders can be allowed with `additional_directories`, which project settings can't set.

## Consequences
- Every file tool is confined by one function with its own tests; new tools get the jail for free
  as long as they use `Workspace.path()`.
- There is a window between the check and the use (a link swapped in between). Only something
  that can already change the file system can exploit it, and today that means `run_shell`.
- The jail doesn't cover `run_shell`: a command can still touch any file. Command analysis and
  permissions (v0.5) and OS sandboxing address that separately.
- A repository that really contains names like `aux.c` can't have those files edited by the
  agent; the error says why.
