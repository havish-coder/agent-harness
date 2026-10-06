# Security Policy

Agent Harness lets a language model run tools on your computer. Treat it like any program
that can read your files and, from v0.2, change them and run commands.

## Current security model (v0.4)
- Tools are bound to a **workspace folder**, but paths are **not yet confined** to it: a path
  such as `../other` or an absolute path can reach files outside it. The path jail arrives in
  v0.5.
- Every tool call that changes something (edits, writes, shell commands) asks for your approval
  first, showing a diff for file changes. Shell commands run with your full rights and
  environment variables: read them before approving.
- API keys belong in environment variables or a git-ignored `.env` file; settings files that
  contain something that looks like a key are refused.
- A project's own settings (`<workspace>/.harness/settings.json`) can't set anything that runs a
  program (`status_line`), and settings that change where prompts are sent (`provider`,
  `base_url`) are shown as a warning at startup. Project commands and styles can't replace the
  built-in ones.

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
