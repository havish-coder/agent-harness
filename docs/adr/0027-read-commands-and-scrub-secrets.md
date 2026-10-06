# 0027. Read shell commands before applying rules, and run them without secrets

- **Status:** Accepted (builds on [0026](0026-permission-modes-and-rules.md))
- **Date:** 2026-10-06

## Context
Lesson 29's rules matched the command as one string, which made allow rules unsafe:
`run_shell(python -m pytest*)` also matched `python -m pytest; rm -rf src` (threat T6, command
smuggling). Users could only guard against it by writing narrow allow rules and broad deny rules.
Two more problems came from the attack lab:

- a shell command inherits the whole environment, so `env` or `echo $ANTHROPIC_API_KEY` hands the
  model your keys, and through it a cloud provider's logs (T7);
- file tools refuse to write to `.git/hooks`, but a command can (`echo x > .git/hooks/pre-commit`,
  `cp`, `sed -i`, `git config core.hooksPath ...`) (T4).

## Options
1. **Keep string matching and document the gap.** Cheap; leaves the most common rule unsafe.
2. **Allow only commands with no shell syntax at all** (no `;`, `&&`, `|`, `$(...)`, redirections).
   Safe and simple; but models write `cd project && python -m pytest` constantly, so users would
   get asked all the time or turn rules off.
3. **Parse the command with a real shell parser.** Exact for one shell; heavy, and we support
   bash and PowerShell on Windows, macOS and Linux.
4. **Read the command with a small purpose-built analyzer** that splits compound commands, looks
   inside `$(...)`, backticks and `bash -c`, sees through wrappers, and *says when it can't follow*;
   rules then apply to each command it found.
5. **Run commands in a sandbox** (container, restricted token, `bwrap`). The only complete answer,
   but not portable to every user's machine; planned as an option in Lesson 35.

For the environment: pass everything (status quo), pass an allowlist (breaks tools that need
`HOME`, `PATH`, proxy settings, locale and a long tail of others), or remove what looks secret.

## Decision
Option 4, in `harness/security/shell.py`, and *remove what looks secret* in
`harness/security/secrets.py`.

- **Analysis** (`analyze(command, dialect)`): the simple commands a line would run, each with its
  words (quotes removed), wrappers stripped (`env`, `sudo`, `timeout`, `nohup`, `xargs`, `NAME=value`
  ...; recorded so they can be refused), redirections, and plain-language risk notes. Anything it
  can't follow goes into `opaque`: here-documents, `eval` of a variable, a program name held in a
  variable, `case`, function definitions, unbalanced quotes, other shells, most PowerShell syntax.
- **Rules.** Deny and ask rules match if *any* command found (or the whole text) matches,
  case-insensitively. Allow rules match only if the line is fully understood and *every* command is
  covered by a pattern rule or is one of a few that need no rule (`cd` inside the workspace, `pwd`,
  `echo`, `printf`, `true`, `false`, `sleep`); a command with a wrapper or an environment prefix is
  never covered; redirection targets must be inside the workspace. A whole-tool allow rule and an
  exact "always" rule keep working for opaque commands: the user chose them knowingly.
- **Protected places.** A command that writes to one with a redirection, or names one in any word
  (except viewers like `cat` and `ls`), asks in every mode; so do `git config` writes and `git -c`.
- **Notes.** The approval question lists the risks found. They inform; they never decide.
- **Secrets.** `run_shell` runs with the environment minus variables whose name contains a secret word
  (KEY, TOKEN, SECRET, PASSWORD, AUTH, COOKIE, CREDENTIALS ...) or whose value looks like an API key.
  `shell_env_keep` (user and local settings only) names exceptions.

## Consequences
- The common rule `run_shell(python -m pytest*)` is now safe to write, and `cd project && python -m
  pytest -q` needs only that one rule. In the replay of the Lesson 24 runs it brings questions per
  `/fix-tests` run from about 2 to 0 without the unsafe `cd * && ...` rule that was needed before.
- The analyzer is an approximation of the shell grammar, kept honest by the `opaque` list: **it
  fails toward asking**, never toward allowing. Its tests (about 90 cases) are the specification.
- It reads text, so a path built at run time (`'.g' + 'it'`) or what a script does is invisible.
  Closing that needs a sandbox; the attack lab keeps it as an expected failure until then.
- Removing secrets by name has false positives (`TOKENIZERS_PARALLELISM` is removed) and some
  tools want a removed variable (`SSH_AUTH_SOCK`); `shell_env_keep` is the escape hatch.
- Secrets in files are untouched; redaction is a later lesson.
