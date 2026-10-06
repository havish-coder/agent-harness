"""Lesson 25b: show LaTeX math readably in a terminal.

Terminals can't typeset, but Unicode has most of what simple math needs:
    $\\frac{1}{2} + x^2 \\leq \\sqrt{\\alpha_i}$   →   ½ + x² ≤ √αᵢ

`render_math(markdown)` finds math in a Markdown answer ($...$, $$...$$, \\(...\\), \\[...\\]),
leaves code alone, doesn't mistake prices ("$5 and $10") for math, and converts each formula.
`to_unicode(latex)` converts one formula. Anything it doesn't understand stays visible as LaTeX
rather than being guessed.
"""
import re

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "varepsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν",
    "xi": "ξ", "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ",
    "upsilon": "υ", "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ",
    "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
SYMBOLS = {
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓", "ast": "∗", "star": "⋆", "circ": "∘",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "approx": "≈", "equiv": "≡",
    "sim": "∼", "simeq": "≃", "cong": "≅", "propto": "∝", "ll": "≪", "gg": "≫",
    "infty": "∞", "partial": "∂", "nabla": "∇", "sum": "∑", "prod": "∏", "int": "∫", "iint": "∬",
    "iiint": "∭", "oint": "∮", "to": "→", "rightarrow": "→", "leftarrow": "←", "gets": "←",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔", "leftrightarrow": "↔", "implies": "⇒",
    "iff": "⇔", "mapsto": "↦", "uparrow": "↑", "downarrow": "↓",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "subseteq": "⊆", "supset": "⊃", "supseteq": "⊇",
    "cup": "∪", "cap": "∩", "setminus": "∖", "emptyset": "∅", "varnothing": "∅",
    "forall": "∀", "exists": "∃", "nexists": "∄", "neg": "¬", "lnot": "¬", "land": "∧", "wedge": "∧",
    "lor": "∨", "vee": "∨", "oplus": "⊕", "otimes": "⊗", "perp": "⊥", "parallel": "∥", "angle": "∠",
    "ldots": "…", "dots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱", "prime": "′", "degree": "°",
    "hbar": "ℏ", "ell": "ℓ", "Re": "ℜ", "Im": "ℑ", "aleph": "ℵ", "therefore": "∴", "because": "∵",
    "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "mid": "∣", "vert": "|", "Vert": "‖", "{": "{", "}": "}", "%": "%", "$": "$", "&": "&", "#": "#", "_": "_",
    ",": " ", ";": " ", ":": " ", " ": " ", "quad": "  ", "qquad": "    ", "!": "", "\\": "; ",
}
FUNCTIONS = {"sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
             "log", "ln", "lg", "exp", "lim", "liminf", "limsup", "max", "min", "sup", "inf", "det", "dim",
             "ker", "deg", "gcd", "arg", "Pr", "mod"}
BLACKBOARD = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ", "P": "ℙ", "E": "𝔼"}
ACCENTS = {"hat": "̂", "bar": "̄", "overline": "̅", "vec": "⃗", "dot": "̇",
           "ddot": "̈", "tilde": "̃", "widehat": "̂", "widetilde": "̃"}
TEXT_WRAPPERS = {"text", "textrm", "textbf", "textit", "textsf", "texttt", "mbox", "operatorname"}
MATH_WRAPPERS = {"mathrm", "mathbf", "mathit", "mathsf", "mathtt", "mathcal", "boldsymbol", "displaystyle"}
SUPER = dict(zip("0123456789+-=()niabcdefghjklmoprstuvwxyzABDEGHIJKLMNOPRTUVW",
                 "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵃᵇᶜᵈᵉᶠᵍʰʲᵏˡᵐᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ", strict=True))
SUPER.update({"′": "′", "*": "*", "∗": "*"})
SUB = dict(zip("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ", strict=True))
FRACTIONS = {("1", "2"): "½", ("1", "3"): "⅓", ("2", "3"): "⅔", ("1", "4"): "¼", ("3", "4"): "¾",
             ("1", "5"): "⅕", ("1", "6"): "⅙", ("1", "8"): "⅛"}
# Relations and binary operators get a space on each side, as in typeset math.
SPACED = set("=+-<>") | set("×·÷±∓≤≥≠≈≡∼≃≅∝≪≫→←⇒⇐⇔↔↦∈∉∋⊂⊆⊃⊇∪∩∖∧∨⊕⊗∣")
# After these come limits (sub/superscripts) and then an operand: "∑ᵢ₌₁ⁿ i", "sin x".
BIG = set("∑∏∫∬∭∮")
OPENERS = "([{⟨⌊⌈|"
WIDE = "\x01"                      # stands for \quad until the end, so space collapsing keeps it


class _Parser:
    """A small recursive-descent reader over a LaTeX math string.

    Spaces in the source are ignored, as LaTeX itself ignores them in math; spacing comes from
    what each symbol is: relations and operators get spaces, a big operator or function is
    followed by one, a comma by one.
    """

    def __init__(self, src: str):
        self.s, self.i = src, 0

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def skip_spaces(self):
        while self.peek() in (" ", "\n", "\t") and self.peek():
            self.i += 1

    def group(self) -> str:
        """The next argument: {…} or a single token, converted."""
        self.skip_spaces()
        if self.peek() == "{":
            self.i += 1
            out = self.expression(stop="}")
            self.i += 1                                   # the closing brace
            return out
        out, _ = self.token()
        return out.strip()

    def raw_group(self) -> str:
        """The next {…} argument as raw text (\\text{...}, \\begin{name}, \\mathbb{R})."""
        self.skip_spaces()
        if self.peek() != "{":
            out, _ = self.token()
            return out
        depth, start = 0, self.i
        while self.i < len(self.s):
            if self.s[self.i] == "{":
                depth += 1
            elif self.s[self.i] == "}":
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return self.s[start + 1:self.i - 1]
            self.i += 1
        return self.s[start + 1:]

    def command(self) -> tuple[str, str]:
        """One \\command → (text, kind) where kind is 'op', 'big' (operand follows) or ''."""
        self.i += 1                                       # the backslash
        m = re.match(r"[A-Za-z]+|.", self.s[self.i:])
        if not m:
            return "\\", ""
        name = m.group(0)
        self.i += len(name)
        if name in ("quad", "qquad"):
            return WIDE, ""
        if name in (",", ";", ":", " "):
            return " ", ""
        if name == "!":
            return "", ""
        if name == "\\":
            return "; ", ""
        if name in GREEK:
            return GREEK[name], ""
        if name in SYMBOLS:
            symbol = SYMBOLS[name]
            return symbol, "op" if symbol in SPACED else "big" if symbol in BIG else ""
        if name in FUNCTIONS:
            return name, "big"
        if name in TEXT_WRAPPERS:
            return self.raw_group(), ""
        if name in MATH_WRAPPERS:
            return self.group(), ""
        if name == "boxed":                                # a boxed final answer: brackets stand in for the box
            return f"[{self.group()}]", ""
        if name in ("frac", "dfrac", "tfrac"):
            top, bottom = self.group(), self.group()
            if (top, bottom) in FRACTIONS:
                return FRACTIONS[(top, bottom)], ""

            def wrap(t):
                return t if re.fullmatch(r"[\w.′]+", t) else f"({t})"
            return f"{wrap(top)}/{wrap(bottom)}", ""
        if name in ("binom", "dbinom", "tbinom"):
            n, k = self.group(), self.group()
            return f"C({n}, {k})", ""
        if name == "sqrt":
            root = ""
            if self.peek() == "[":
                end = self.s.find("]", self.i)
                root, self.i = self.s[self.i + 1:end], end + 1
            body = self.group()
            sign = {"": "√", "3": "∛", "4": "∜"}.get(root, f"{to_super(root) or root}√")
            return (f"{sign}{body}" if re.fullmatch(r"\w+", body) else f"{sign}({body})"), ""
        if name in ACCENTS:
            return self.group() + ACCENTS[name], ""
        if name == "mathbb":
            return "".join(BLACKBOARD.get(c, c) for c in self.raw_group()), ""
        if name in ("left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr"):
            self.skip_spaces()
            if self.peek() == ".":
                self.i += 1
                return "", ""
            return self.token()                            # \left( → (
        if name == "begin":
            env = self.raw_group()
            if env in ("array", "tabular"):
                self.raw_group()                          # column spec
            return {"pmatrix": "(", "bmatrix": "[", "vmatrix": "|", "cases": "{ "}.get(env, ""), ""
        if name == "end":
            return {"pmatrix": ")", "bmatrix": "]", "vmatrix": "|"}.get(self.raw_group(), ""), ""
        if self.peek() == "{":                             # unknown: keep it visible, unguessed
            return f"\\{name}{{{self.raw_group()}}}", ""
        return f"\\{name}", ""

    def token(self) -> tuple[str, str]:
        c = self.peek()
        if not c:
            return "", ""
        if c == "\\":
            return self.command()
        self.i += 1
        if c in "&~":
            return " ", ""
        if c == ",":
            return ", ", ""
        return c, "op" if c in SPACED else ""

    def expression(self, stop: str = "") -> str:
        out: list[str] = []
        operand_follows = False                           # after ∑, ∫, sin, lim ... and their limits
        while self.i < len(self.s) and self.peek() != stop:
            c = self.peek()
            if c in " \n\t":
                self.i += 1
                continue
            if c in "^_":
                self.i += 1
                arg = self.group()
                converted = to_super(arg) if c == "^" else to_sub(arg)
                if converted is None:
                    bare = arg.replace(" ", "")
                    converted = f"{c}({bare})" if len(bare) > 1 else f"{c}{bare}"
                out.append(converted)
                continue
            if c == "{":
                text, kind = self.group(), ""
            else:
                text, kind = self.token()
            if operand_follows and text and text != "(" and not text.startswith(" "):   # sin(x), lim (a)/b
                out.append(" ")
            operand_follows = kind == "big"
            if kind == "op":
                previous = "".join(out).rstrip()
                unary = text in "+-±∓" and (not previous or previous[-1] in OPENERS + "".join(SPACED) + ",")
                out.append(text if unary else f" {text} ")
            else:
                out.append(text)
        return "".join(out)


def to_super(text: str) -> str | None:
    """'2' → '²', 'n+1' → 'ⁿ⁺¹'; None if some character has no superscript form."""
    text = text.replace(" ", "")
    return "".join(SUPER[c] for c in text) if text and all(c in SUPER for c in text) else None


def to_sub(text: str) -> str | None:
    text = text.replace(" ", "")
    return "".join(SUB[c] for c in text) if text and all(c in SUB for c in text) else None


def to_unicode(latex: str) -> str:
    """Convert one LaTeX math expression to readable Unicode text."""
    out = _Parser(latex.strip()).expression()
    out = re.sub(r" {2,}", " ", out)
    out = re.sub(r"([(\[{]) ", r"\1", out)
    out = re.sub(r" ([)\]}])", r"\1", out)
    out = re.sub(r" ,", ",", out)
    return out.replace(WIDE, "  ").strip()


# --- finding math inside a Markdown answer -------------------------------------------------------

CODE = re.compile(r"```.*?(?:```|\Z)|`[^`\n]*`", re.DOTALL)
DISPLAY = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.DOTALL)
INLINE = re.compile(r"\\\((.+?)\\\)|(?<![\\$\w])\$(?=\S)([^$\n]*?\S)\$(?![\d$])")


# Models often pad inline math: `$ a \neq 0 $`. Markdown and pandoc don't accept that as math (no
# space may follow the opening or precede the closing dollar), so it is tightened first. Measured
# (Lesson 25b): qwen3:4b-instruct wrote padded math in 3 of 3 answers. To keep money out ("costs
# $ 5 and $ 10"), the padded text must look like math: a command, ^, _, =, brackets, or one letter.
PADDED = re.compile(r"(?<![\\$\w])\$ ([^$\n]*?) \$(?![\d$])")
LOOKS_LIKE_MATH = re.compile(r"\\[A-Za-z]|[\^_=<>{}]|^\s*[A-Za-z]\s*$")


def tighten(markdown: str) -> str:
    """`$ x^2 $` → `$x^2$` outside code, so every renderer treats it as math."""
    def fix(text: str) -> str:
        return PADDED.sub(lambda m: f"${m.group(1).strip()}$" if LOOKS_LIKE_MATH.search(m.group(1)) else m.group(0), text)
    pieces, last = [], 0
    for m in CODE.finditer(markdown):
        pieces += [fix(markdown[last:m.start()]), m.group(0)]
        last = m.end()
    pieces.append(fix(markdown[last:]))
    return "".join(pieces)


def render_math(markdown: str) -> str:
    """Replace math in Markdown with Unicode; display formulas become their own quoted paragraph."""
    markdown = tighten(markdown)
    pieces, last = [], 0
    for m in CODE.finditer(markdown):                     # never touch code
        pieces.append(_render_text(markdown[last:m.start()]))
        pieces.append(m.group(0))
        last = m.end()
    pieces.append(_render_text(markdown[last:]))
    return "".join(pieces)


def _render_text(text: str) -> str:
    text = DISPLAY.sub(lambda m: f"\n\n> {to_unicode(m.group(1) or m.group(2))}\n\n", text)
    return INLINE.sub(lambda m: to_unicode(m.group(1) or m.group(2)), text)
