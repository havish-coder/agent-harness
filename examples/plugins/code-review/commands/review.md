---
description: review your uncommitted changes, or a file you name
argument-hint: [file, or what to focus on]
---
Review code in this project. Language: {{language}}. Strictness: {{strictness}}.

What to review: $ARGUMENTS
If that is empty, review the uncommitted changes: run `git diff` (and `git diff --staged`). If this isn't a git repository, ask which file to review.

Read the code before you judge it: open the files, and the code around each change. Then report at most {{max_findings}} findings, the most important first. For each one:
- the file and line,
- what is wrong, and what happens because of it (a wrong result, a crash, a security hole, code that is hard to change),
- the fix, in one or two lines of code if you can.

At strictness "gentle", report only bugs. At "normal", bugs and code that is hard to follow. At "strict", also naming, style, and missing tests.
If the language is not "any", check that language's usual conventions and pitfalls.

Don't change any file: this is a review. If you find nothing worth reporting, say so in one line.
