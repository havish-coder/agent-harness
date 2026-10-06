# Math and PDF export

## Math in answers
Models write formulas in LaTeX: `$\frac{n(n+1)}{2}$` inline, `$$ ... $$` on its own line. The
terminal can't typeset, so the rich interface shows them with Unicode symbols instead:

| The model writes | You see |
|---|---|
| `$x^2 + y^2 = z^2$` | x² + y² = z² |
| `$\frac{1}{2}$`, `$\frac{a}{b}$`, `$\frac{x+1}{y-2}$` | ½, a/b, (x + 1)/(y - 2) |
| `$\sqrt{2}$`, `$\sqrt[3]{8}$` | √2, ∛8 |
| `$\sum_{i=1}^{n} i$` | ∑ᵢ₌₁ⁿ i |
| `$\forall x \in \mathbb{R}, x^2 \geq 0$` | ∀x ∈ ℝ, x² ≥ 0 |
| `$\alpha, \beta, \pi$` | α, β, π |

Formulas on their own line (`$$...$$` or `\[...\]`) appear as a separate, indented block.
Anything the converter doesn't know stays visible as LaTeX rather than being guessed, prices
like `$5 and $10` are left alone, and code (in backticks or code blocks) is never changed.
Models often write padded math (`$ x^2 $` with spaces inside the dollars), which Markdown and
pandoc don't treat as math; the harness closes those spaces first, in the terminal and in exports,
when the text looks like math (a command, `^`, `_`, `=`, brackets, or a single letter), so `$ 5 and $ 10`
is still money. A `oxed{...}` answer is shown in square brackets.
In plain mode (`--plain`, pipes) answers are shown exactly as the model wrote them.

To make the model use LaTeX for math consistently, switch to the `latex` style:

```text
/style latex
```

(see [output styles](styles-and-status.md)).

## Export a chat
```text
/export                     the whole chat as a PDF
/export md                  as Markdown
/export tex                 as a LaTeX document
/export pdf report.pdf      choose the file name (relative to the workspace)
/export pdf --last          only the last answer
```

Without a file name, exports go to `<workspace>/.harness/exports/chat-<date>-<time>.<ext>`. The
document has your messages, the agent's answers (math typeset properly), and one line per tool
the agent used; tool output and attached files are left out.

### What you need
| Format | Needs |
|---|---|
| `md` | nothing |
| `tex` | [pandoc](https://pandoc.org) |
| `pdf` | pandoc and [Tectonic](https://tectonic-typesetting.github.io) |

The agent finds them on your `PATH` or anywhere under `~/.harness/tools/` (for example
`~/.harness/tools/pandoc-3.12/pandoc.exe` and `~/.harness/tools/tectonic/tectonic.exe`, unzipped
from their release downloads). If one is missing, `/export` says which, and writes what it can
instead (the `.md`, or the `.tex` to compile elsewhere, e.g. on Overleaf).

The first PDF takes about a minute: Tectonic downloads the LaTeX packages it needs and caches
them. Later exports take a few seconds. PDFs use the Cambria, Consolas and Cambria Math fonts that
come with Windows.
