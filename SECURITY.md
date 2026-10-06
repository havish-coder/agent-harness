# Security Policy

Agent Harness lets a language model run tools on your computer. Treat it like any program
that can read your files and, from v0.2, change them and run commands.

## Current security model (v0.1)
- Tools are bound to a **workspace folder**, but paths are **not yet confined** to it: a path
  such as `../other` or an absolute path can reach files outside it. A path jail arrives in
  v0.5.
- From v0.2 the agent can edit files and run shell commands. Every such call asks for your
  approval in the terminal first, showing a diff for file changes. Shell commands run with
  your full rights and environment variables: read them before approving.

Use a dedicated workspace folder and don't point the agent at folders containing secrets.

See [docs/security.md](docs/security.md) for the threat model and the planned defenses.

## Reporting a vulnerability
Please **don't open a public issue** for a security problem. Use GitHub's private
vulnerability reporting ("Security" tab → "Report a vulnerability") on
<https://github.com/havish-coder/agent-harness>. Include steps to reproduce and the version
or commit you tested.

## Supported versions
Only the latest release receives fixes while the project is below 1.0.
