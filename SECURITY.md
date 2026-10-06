# Security Policy

Agent Harness lets a language model run tools on your computer. Treat it like any program
that can read your files, change them, run commands and fetch web pages.

## Current security model (v0.5)
- **Path jail.** File tools only reach the workspace (and folders you list in `additional_directories`),
  however a path is written: `..`, absolute paths, drive letters, links, Windows junctions and device names.
- **Permissions.** Anything that changes something asks, unless you choose a mode (`accept-edits`, `plan`,
  `bypass`) or write allow, ask and deny rules. The strictest answer wins; protected places (`.git`, `.harness`,
  CI folders, ...) always ask. A project's settings can tighten this, never loosen it.
- **Shell commands are read before they run**: compound commands are split, hidden commands inside `$(...)`
  and `bash -c` are found, risks are listed in the question, and secret environment variables are removed.
- **Untrusted content** (web pages, and files in folders you haven't trusted) is fenced as data, and after the
  agent has read it, blanket approvals pause.
- **Web pages** are fetched from public servers only, with the checked address connected to, redirects checked.
- **Secrets** are hidden from tool results and exports; an audit log, hooks of your own, and per-chat limits
  (calls, cost) are available. Commands can run in an OS sandbox on Linux and macOS (not on Windows).
- Details, and what each defense does *not* cover, are in [docs/security.md](docs/security.md).

Earlier basics still hold:
- By default every tool call that changes something (edits, writes, shell commands) asks for your
  approval first, showing a diff for file changes. Shell commands run with your rights (minus
  secret environment variables): read them before approving.
- API keys belong in environment variables or a git-ignored `.env` file; settings files that
  contain something that looks like a key are refused.
- A project's own settings (`<workspace>/.harness/settings.json`) can't set anything that runs a
  program (`status_line`; hooks only in a folder you trust), grant access or approvals, or switch
  a protection off. Settings that change where prompts are sent (`provider`, `base_url`) are
  shown as a warning at startup. Project commands and styles can't replace the built-in ones.

Use a dedicated workspace folder and don't point the agent at folders containing secrets.

See [docs/security.md](docs/security.md) for the threat model: what is protected, from whom,
and which defense covers which threat.

## Reporting a vulnerability
Please **don't open a public issue** for a security problem. Use GitHub's private
vulnerability reporting ("Security" tab → "Report a vulnerability") on
<https://github.com/havish-coder/agent-harness>. Include steps to reproduce and the version
or commit you tested.

## Supported versions
Only the latest release receives fixes while the project is below 1.0.
