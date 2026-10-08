// Lesson 54: Markdown and code for the page, safe by construction: every piece of text is escaped first, and only then are
// the few tags chosen here added. No raw HTML, no images (a picture's address can carry data out), links only to http(s).
// Pure functions, no DOM: tests/test_web_page.py runs them in Node.
"use strict";
const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function inline(s) {
  const codes = [];
  s = s.replace(/\u0000/g, "").replace(/`([^`\n]+)`/g, (_, c) => "\u0000" + (codes.push(c) - 1) + "\u0000");
  s = esc(s)
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '<span class="img">[image: $1]</span>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>")
    .replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => "<code>" + esc(codes[+i]) + "</code>");
}

const BLOCK = /^\s*(```|#{1,6}\s|>|[-*+]\s|\d+[.)]\s|\|)/;
const ITEM = /^\s*([-*+]|\d+[.)])\s+/;
function md(source) {
  const lines = source.replace(/\r/g, "").split("\n"), out = [];
  let i = 0, m;
  while (i < lines.length) {
    const line = lines[i];
    if ((m = line.match(/^\s*```\s*([\w+#.-]*)/))) {
      const body = [];
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) body.push(lines[i]);
      i++;
      out.push(`<pre><code>${highlight(body.join("\n"), m[1])}</code></pre>`);
    } else if ((m = line.match(/^(#{1,6})\s+(.*)/))) {
      const level = Math.min(4, m[1].length);
      out.push(`<h${level}>${inline(m[2])}</h${level}>`);
      i++;
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      out.push("<hr>");
      i++;
    } else if (/^\s*>/.test(line)) {
      const quoted = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) quoted.push(lines[i++].replace(/^\s*> ?/, ""));
      out.push(`<blockquote>${md(quoted.join("\n"))}</blockquote>`);
    } else if (ITEM.test(line)) {
      const ordered = /^\s*\d/.test(line), items = [], start = ordered ? parseInt(line.match(/\d+/)[0], 10) : 1;
      for (;;) {
        // a blank line between two items of the same list doesn't end it (models write "1. a\n\n2. b")
        if (i + 1 < lines.length && !lines[i].trim() && ITEM.test(lines[i + 1]) && /^\s*\d/.test(lines[i + 1]) === ordered && items.length) i++;
        if (!(i < lines.length && (ITEM.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length)))) break;
        const item = lines[i].match(/^(\s*)(?:[-*+]|\d+[.)])\s+(.*)/);
        if (item) items.push(`<li${item[1].length >= 2 ? ' class="sub"' : ""}>${inline(item[2])}</li>`);
        else items[items.length - 1] = items[items.length - 1].replace(/<\/li>$/, " " + inline(lines[i].trim()) + "</li>");
        i++;
      }
      out.push(ordered ? `<ol${start > 1 ? ` start="${start}"` : ""}>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
    } else if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?[\s:|-]*-[\s:|-]*$/.test(lines[i + 1] || "")) {
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      let html = "<table><tr>" + cells(line).map((c) => `<th>${c}</th>`).join("") + "</tr>";
      for (i += 2; i < lines.length && /^\s*\|/.test(lines[i]); i++) html += "<tr>" + cells(lines[i]).map((c) => `<td>${c}</td>`).join("") + "</tr>";
      out.push(html + "</table>");
    } else if (!line.trim()) {
      i++;
    } else {
      const para = [];
      while (i < lines.length && lines[i].trim() && !(para.length && BLOCK.test(lines[i]))) para.push(inline(lines[i++]));
      out.push(`<p>${para.join("<br>")}</p>`);
    }
  }
  return out.join("");
}

// A small highlighter: comments, strings, numbers, keywords, calls. Every piece it emits is escaped.
const KEYWORDS = new Set(("def class return import from as if elif else for while try except finally with lambda yield raise pass break continue in " +
  "not and or is None True False async await function const let var new export default switch case this null undefined true false public private " +
  "static void int fn pub use mut struct impl match package func type interface").split(" "));
const HASH_COMMENTS = new Set(["py", "python", "sh", "bash", "zsh", "ps1", "powershell", "rb", "ruby", "yaml", "yml", "toml", "r", "pl", "conf", "ini", "dockerfile", "makefile"]);
const PLAIN = new Set(["", "md", "markdown", "txt", "text", "log", "csv", "diff"]);
function highlight(code, lang) {
  lang = (lang || "").toLowerCase();
  if (PLAIN.has(lang)) return esc(code);
  const comment = HASH_COMMENTS.has(lang) ? "#[^\\n]*" : "\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/";
  const re = new RegExp(`(${comment})|("""[\\s\\S]*?"""|'''[\\s\\S]*?'''|"(?:[^"\\\\\\n]|\\\\.)*"|'(?:[^'\\\\\\n]|\\\\.)*'|\`[^\`]*\`)|\\b(\\d+(?:\\.\\d+)?)\\b|\\b([A-Za-z_]\\w*)\\b`, "g");
  let html = "", last = 0, m;
  while ((m = re.exec(code))) {
    html += esc(code.slice(last, m.index));
    if (m[1]) html += `<span class="c">${esc(m[1])}</span>`;
    else if (m[2]) html += `<span class="s">${esc(m[2])}</span>`;
    else if (m[3]) html += `<span class="n">${m[3]}</span>`;
    else if (KEYWORDS.has(m[4])) html += `<span class="k">${m[4]}</span>`;
    else html += code[re.lastIndex] === "(" ? `<span class="f">${m[4]}</span>` : m[4];
    last = re.lastIndex;
  }
  return html + esc(code.slice(last));
}
