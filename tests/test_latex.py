"""Lesson 25b: LaTeX math shown as Unicode in the terminal."""
import pytest

from harness.tui.latex import render_math, tighten, to_super, to_unicode


@pytest.mark.parametrize("latex,expected", [
    (r"x^2 + y^2 = z^2", "x² + y² = z²"),
    (r"\frac{1}{2}", "½"),
    (r"\frac{a}{b}", "a/b"),
    (r"\frac{x+1}{y-2}", "(x + 1)/(y - 2)"),
    (r"\frac{\alpha}{\beta}", "α/β"),
    (r"\sqrt{2}", "√2"),
    (r"\sqrt{x+1}", "√(x + 1)"),
    (r"\sqrt[3]{8}", "∛8"),
    (r"a_i + a_{n-1}", "aᵢ + aₙ₋₁"),
    (r"e^{i\pi} + 1 = 0", "e^(iπ) + 1 = 0"),          # no superscript π: written out, not guessed
    (r"\sum_{i=1}^{n} i = \frac{n(n+1)}{2}", "∑ᵢ₌₁ⁿ i = (n(n + 1))/2"),
    (r"\int_0^\infty e^{-x}\,dx = 1", "∫₀^∞ e⁻ˣ dx = 1"),
    (r"\forall x \in \mathbb{R}, x^2 \geq 0", "∀x ∈ ℝ, x² ≥ 0"),
    (r"\lim_{x \to 0} \frac{\sin x}{x} = 1", "lim_(x→0) (sin x)/x = 1"),
    (r"\left( \frac{a}{b} \right)^2", "(a/b)²"),
    (r"\text{area} = \pi r^2", "area = πr²"),
    (r"\hat{x}", "x̂"),
    (r"\binom{n}{k}", "C(n, k)"),
    (r"P(A \mid B) \propto P(B \mid A)\,P(A)", "P(A ∣ B) ∝ P(B ∣ A) P(A)"),
    (r"\unknowncommand{x}", r"\unknowncommand{x}"),   # stays visible, unguessed
])
def test_to_unicode(latex, expected):
    assert to_unicode(latex) == expected


def test_unary_minus_and_text_spaces():
    assert to_unicode(r"-x + \text{rate of change}") == "-x + rate of change"
    assert to_unicode(r"f(x, y) = \sin(x) \cdot y") == "f(x, y) = sin(x) · y"
    assert to_unicode(r"a \quad b") == "a  b"


def test_superscripts_only_when_every_character_has_one():
    assert to_super("n+1") == "ⁿ⁺¹" and to_super("π") is None and to_super("") is None


def test_render_math_inline_and_display():
    md = "The area is $\\pi r^2$, and\n\n$$\\int_0^1 x\\,dx = \\frac{1}{2}$$\n\ndone."
    out = render_math(md)
    assert "The area is πr²" in out
    assert "> ∫₀¹ x dx = ½" in out
    assert "$" not in out


def test_money_and_code_are_left_alone():
    assert render_math("It costs $5 and $10, or $3.50.") == "It costs $5 and $10, or $3.50."
    assert render_math("Run `echo $HOME $PATH` now") == "Run `echo $HOME $PATH` now"
    fenced = "```python\nprice = f'${x}' + '$y$'\n```"
    assert render_math(fenced) == fenced
    assert render_math("between $1 and $2 per $x$ unit") == "between $1 and $2 per x unit"


def test_other_delimiters():
    assert render_math(r"so \(a^2\) and \[b_0\]") == "so a² and \n\n> b₀\n\n"


def test_padded_inline_math_is_math():
    r"""qwen3:4b-instruct writes `$ a \neq 0 $` with spaces inside the dollars (Lesson 25b)."""
    out = render_math(r"where $ a \neq 0 $ and $ x $, with $ x^2 = 4 $.")
    assert out == "where a ≠ 0 and x, with x² = 4."


def test_padded_dollars_around_money_stay_money():
    text = "It cost $ 5 and then $ 10 more."
    assert render_math(text) == text
    assert tighten(text) == text


def test_tighten_rewrites_math_but_not_code():
    assert tighten(r"set $ x^2 $ now") == r"set $x^2$ now"
    code = "run `a $ x^2 $ b` and\n```\n$ y = 1 $\n```"
    assert tighten(code) == code


def test_boxed_answers():
    assert to_unicode(r"\boxed{\frac{1}{\sigma\sqrt{2\pi}}}") == "[1/(σ√2π)]"
