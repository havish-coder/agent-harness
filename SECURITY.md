# Security Policy

Agent Harness lets a language model run tools on your computer. Treat it like any program
that can read your files and, from v0.2, change them and run commands.

## Current security model (v0.1)
- Tools are bound to a **workspace folder**, but paths are **not yet confined** to it: a path
  such as `../other` or an absolute path can reach files outside it. A path jail arrives in
  v0.5.
- All v0.1 tools are read-only.
- Starting with v0.2, every tool that can change something asks for your approval in the
  terminal before it runs.

Use a dedicated workspace folder and don't point the agent at folders containing secrets.

See [docs/security.md](docs/security.md) for the threat model and the planned defenses.

## Reporting a vulnerability
Please **don't open a public issue** for a security problem. Use GitHub's private
vulnerability reporting ("Security" tab → "Report a vulnerability") on
<https://github.com/havish-coder/agent-harness>. Include steps to reproduce and the version
or commit you tested.

## Supported versions
Only the latest release receives fixes while the project is below 1.0.
