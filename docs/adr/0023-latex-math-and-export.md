# 0023. Our own LaTeX-to-Unicode converter for the terminal; pandoc and Tectonic for documents

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Users want the agent's answers to look good, including formulas, which models write in LaTeX.
A terminal can't typeset; raw LaTeX like `\frac{n(n+1)}{2}` is hard to read. Users also want to
keep good answers as proper documents.

## Options
For the terminal:
1. **Show raw LaTeX**: no work; unreadable.
2. **A LaTeX-to-text library** (e.g. pylatexenc): broad coverage; a new dependency for a narrow job.
3. **Our own converter** for the math models actually write: Greek letters, operators, fractions,
   roots, sub- and superscripts (Unicode has many), big operators, `\mathbb`, `\text`.

For documents:
4. **Write LaTeX by hand from Markdown**: a large converter to maintain.
5. **pandoc** (Markdown → LaTeX/PDF) with **Tectonic** (a self-contained LaTeX engine), both optional
   external programs.

## Decision
Option 3 in `harness/tui/latex.py`, applied by the rich UI only; unknown commands are left visible
rather than guessed, and math detection skips code and prices. Option 5 for `/export`, looking for
the tools on `PATH` and in `~/.harness/tools/`, and degrading to what can be produced when one is
missing.

## Consequences
- No new Python dependency; the converter covers common math and is tested case by case.
- Superscripts only exist for some characters (`e^{iπ}` becomes `e^(iπ)`); that's the limit of
  plain text.
- PDF export depends on two external programs (about 60 MB) and, on first use, Tectonic's package
  download. Fonts without some glyphs (e.g. ✓ in Cambria) are worked around by writing those
  characters as LaTeX commands.
