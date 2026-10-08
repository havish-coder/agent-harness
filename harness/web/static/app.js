// Lesson 54: the dashboard. The conversation so far comes from /api/state, then /events streams what happens next; both go
// through show(), so a reload draws exactly what a live page drew. Model text becomes HTML only through md() (markdown.js),
// which escapes everything first; everything else goes in with textContent.
"use strict";
const $ = (id) => document.getElementById(id);
const chat = $("chat"), term = $("term"), logBox = $("log"), text = $("text");

function el(tag, cls, words) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (words !== undefined) e.textContent = words;
  return e;
}
const clock = () => new Date().toTimeString().slice(0, 8);
const nearBottom = (box) => box.scrollHeight - box.scrollTop - box.clientHeight < 90;
function append(box, node) {
  const follow = nearBottom(box);
  box.appendChild(node);
  if (follow) box.scrollTop = box.scrollHeight;
  return node;
}
const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

// --- the run graph: requests, their tool calls, sub-agents, answers; a small force layout in SVG --------------------------------
const SVG = "http://www.w3.org/2000/svg";
const MAX_NODES = 160;
class Graph {
  constructor(svg) {
    this.svg = svg;
    this.links = svg.appendChild(document.createElementNS(SVG, "g"));
    this.dots = svg.appendChild(document.createElementNS(SVG, "g"));
    this.nodes = [];
    this.edges = [];
    this.byId = new Map();
    this.view = { x: -150, y: -110, w: 300, h: 220 };
    this.heat = 0;
  }
  add(id, kind, label, parentId, title) {
    const parent = parentId ? this.byId.get(parentId) : null;
    const angle = Math.random() * Math.PI * 2;
    const n = { id, kind, label, vx: 0, vy: 0, status: "ok",
                x: (parent ? parent.x : 0) + Math.cos(angle) * 30, y: (parent ? parent.y : 0) + Math.sin(angle) * 30 };
    n.g = document.createElementNS(SVG, "g");
    const circle = document.createElementNS(SVG, "circle");
    circle.setAttribute("r", { request: 9, agent: 7, tool: 5, answer: 4 }[kind]);
    const caption = document.createElementNS(SVG, "text");
    caption.setAttribute("y", kind === "request" ? 21 : 15);
    caption.textContent = short(label, 16);
    const tip = document.createElementNS(SVG, "title");
    tip.textContent = title || label;
    n.g.append(circle, caption, tip);
    n.g.addEventListener("click", () => this.onClick && this.onClick(n));
    this.dots.appendChild(n.g);
    this.nodes.push(n);
    this.byId.set(id, n);
    if (parent) this.link(parent, n, kind === "request" ? "chain" : "");
    this.setStatus(id, kind === "tool" || kind === "agent" ? "running" : "ok");
    this.trim();
    this.kick();
    $("graph-count").textContent = this.nodes.length + " nodes";
    return n;
  }
  link(a, b, cls) {
    const line = document.createElementNS(SVG, "line");
    if (cls) line.setAttribute("class", cls);
    this.links.appendChild(line);
    this.edges.push({ a, b, line });
  }
  setStatus(id, status) {
    const n = this.byId.get(id);
    if (!n) return;
    n.status = status;
    n.g.setAttribute("class", `node ${n.kind} ${status}${n.stale ? " stale" : ""}`);
  }
  stale(ids) {
    for (const id of ids) { const n = this.byId.get(id); if (n) { n.stale = true; this.setStatus(id, n.status); } }
  }
  trim() {
    while (this.nodes.length > MAX_NODES) {
      const old = this.nodes.shift();
      old.g.remove();
      this.byId.delete(old.id);
      this.edges = this.edges.filter((e) => (e.a === old || e.b === old ? (e.line.remove(), false) : true));
    }
  }
  kick() {
    this.heat = 1;
    if (!this.running) { this.running = true; requestAnimationFrame(() => this.tick()); }
  }
  tick() {
    const N = this.nodes;
    for (let i = 0; i < N.length; i++) {
      for (let j = i + 1; j < N.length; j++) {
        const a = N[i], b = N[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        const d2 = dx * dx + dy * dy + 0.01;
        if (d2 > 40000) continue;
        const f = 260 / d2;
        dx *= f; dy *= f;
        a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy;
      }
    }
    for (const { a, b } of this.edges) {
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const want = b.kind === "request" ? 95 : b.kind === "agent" ? 50 : 38;
      const f = ((d - want) / d) * 0.04;
      a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
    }
    for (const n of N) {
      n.vx = (n.vx - n.x * 0.002) * 0.78;
      n.vy = (n.vy - n.y * 0.002) * 0.78;
      n.x += Math.max(-8, Math.min(8, n.vx));
      n.y += Math.max(-8, Math.min(8, n.vy));
    }
    this.draw();
    this.heat *= 0.988;
    if (this.heat > 0.03) requestAnimationFrame(() => this.tick());
    else this.running = false;
  }
  draw() {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of this.nodes) {
      n.g.setAttribute("transform", `translate(${n.x.toFixed(1)},${n.y.toFixed(1)})`);
      x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x); y1 = Math.max(y1, n.y);
    }
    for (const { a, b, line } of this.edges) {
      line.setAttribute("x1", a.x.toFixed(1)); line.setAttribute("y1", a.y.toFixed(1));
      line.setAttribute("x2", b.x.toFixed(1)); line.setAttribute("y2", b.y.toFixed(1));
    }
    if (!this.nodes.length) return;
    const box = this.svg.getBoundingClientRect(), ratio = box.width / Math.max(1, box.height);
    let w = Math.max(360, x1 - x0 + 80), h = Math.max(260, y1 - y0 + 80);      // a few nodes stay small, in the middle
    if (w / h > ratio) h = w / ratio; else w = h * ratio;
    const v = this.view, ease = 0.15;                      // glide towards the box that fits everything
    v.x += ((x0 + x1) / 2 - w / 2 - v.x) * ease; v.y += ((y0 + y1) / 2 - h / 2 - v.y) * ease;
    v.w += (w - v.w) * ease; v.h += (h - v.h) * ease;
    this.svg.setAttribute("viewBox", `${v.x.toFixed(1)} ${v.y.toFixed(1)} ${v.w.toFixed(1)} ${v.h.toFixed(1)}`);
  }
}
const graph = new Graph($("graph"));

// --- what the page remembers ---------------------------------------------------------------------------------------------
const calls = new Map();           // tool call id -> {box, name, args, node}
const changed = new Set();         // files the agent wrote in this session (the explorer marks them)
let request = null;                // the current request: {node, els: [], nodes: []}
let requests = 0, agents = 0;
let stream = null;                 // the reply being streamed: {box, body, text}
let lastStreamed = null;           // the reply streamed last: the final answer usually repeats it
let thinking = null;
let busy = false;
let currentAgent = null;           // the graph node of a sub-agent at work

function chatItem(node) {
  append(chat, node);
  if (request) request.els.push(node);
  return node;
}
function agentBubble() {
  const box = el("div", "msg agent");
  box.appendChild(el("div", "who", "AGENT"));
  const body = box.appendChild(el("div", "md"));
  chatItem(box);
  return { box, body, text: "" };
}
function system(kind, words) {
  chatItem(el("div", "sys " + kind, words));
}
function logLine(cls, words, live) {
  const line = el("div");
  line.appendChild(el("span", "t", live ? clock() : "--:--:--"));
  line.appendChild(el("span", cls, words));
  append(logBox, line);
  while (logBox.childElementCount > 600) logBox.firstChild.remove();
}
function termLine(cls, words, live) {
  const line = el("div", cls);
  if (cls !== "cmd") line.prepend(el("span", "t", live ? clock() : "--:--:--"));
  line.appendChild(document.createTextNode(words));
  append(term, line);
  while (term.childElementCount > 800) term.firstChild.remove();
}
function setState(words) {
  $("current-state").textContent = words;
}

const SUBJECT = ["path", "command", "pattern", "url", "query", "task", "name", "question"];
function subjectOf(args) {
  for (const k of SUBJECT) if (typeof args[k] === "string") return [k, args[k]];
  const first = Object.entries(args)[0];
  return first ? [first[0], JSON.stringify(first[1])] : ["", ""];
}
const cleanPath = (p) => p.replace(/\\/g, "/").replace(/^\.\//, "");

function toolCall(e, live) {
  const [key, subject] = subjectOf(e.args || {});
  const box = el("div", "call running");
  const head = box.appendChild(el("div", "call-head"));
  head.append(el("span", "state"), el("span", "tool", e.name));
  const sub = head.appendChild(el("span", "subject"));
  if (key === "path") {
    const link = sub.appendChild(el("a", "", subject));
    link.addEventListener("click", (ev) => { ev.stopPropagation(); openFile(cleanPath(subject)); });
  } else {
    sub.textContent = short(subject.replace(/\s+/g, " "), 120);
  }
  head.appendChild(el("span", "chars"));
  const result = box.appendChild(el("pre", "hidden"));
  head.addEventListener("click", () => result.classList.toggle("hidden"));
  chatItem(box);
  const node = graph.add(e.id, "tool", e.name, request && request.node.id, `${e.name} ${subject}`);
  if (request) request.nodes.push(e.id);
  calls.set(e.id, { box, result, name: e.name, args: e.args || {}, head });
  logLine("tool", `→ ${e.name} ${short(subject, 60)}`, live);
  if (e.name === "run_shell") termLine("cmd", e.args.command || "", live);
  setState(`running ${e.name}`);
  return node;
}

function toolResult(e, live) {
  const call = calls.get(e.id);
  const status = e.error ? "error" : "ok";
  graph.setStatus(e.id, status);
  if (!call) return;
  call.box.className = "call " + status;
  call.result.textContent = e.text + (e.chars > e.text.length ? `\n… (${e.chars.toLocaleString()} characters in all)` : "");
  call.head.lastChild.textContent = e.error ? "error" : `${e.chars.toLocaleString()} chars`;
  if (e.name === "run_shell") termLine(e.error ? "bad" : "out", e.text, live);
  if (e.error) logLine("bad", `✗ ${e.name}: ${short(e.text.split("\n")[0], 80)}`, live);
  if (!e.error && (e.name === "edit_file" || e.name === "write_file") && call.args.path) {
    changed.add(cleanPath(call.args.path));
    refreshTree();
    if ($("file-tab").dataset.path === cleanPath(call.args.path)) openFile(cleanPath(call.args.path), false);
  }
  setState("thinking…");
}

function notRun(e, live) {
  graph.setStatus(e.id, "denied");
  const call = calls.get(e.id);
  if (call) { call.box.className = "call denied"; call.head.lastChild.textContent = "not run"; }
  logLine("warn", `○ not run: ${e.reason}`, live);
}

// --- every event, live or from the saved state, comes through here ---------------------------------------------------------------
function show(e, live = true) {
  switch (e.type) {
    case "user": {
      requests += 1;
      const box = el("div", "msg user");
      box.appendChild(el("div", "who", "YOU"));
      box.appendChild(document.createTextNode(e.text));
      const id = "request-" + requests;
      const previous = request && request.node.id;
      request = { node: graph.add(id, "request", e.text.split(/\s+/).slice(0, 3).join(" "), previous, e.text), els: [], nodes: [id] };
      chatItem(box);
      chat.scrollTop = chat.scrollHeight;
      $("current-text").textContent = e.text;
      logLine("you", `you: ${short(e.text, 70)}`, live);
      lastStreamed = null;
      break;
    }
    case "busy":
      busy = e.busy;
      $("send").disabled = busy;
      $("stop").hidden = !busy;
      $("mode").disabled = busy;
      $("main").classList.toggle("live", busy);
      $("busy-chip").textContent = busy ? "working" : "idle";
      $("busy-chip").classList.toggle("working", busy);
      setState(busy ? "thinking…" : "idle");
      if (!busy) { currentAgent = null; stream = null; thinking = null; }
      if (e.status) status(e.status);
      break;
    case "context":
      meter(e.tokens, e.window, e.level);
      termLine(e.level === "ok" ? "out" : "warn", `context ${(e.tokens / 1000).toFixed(1)}k of ${(e.window / 1000).toFixed(1)}k · ${e.level}`, live);
      break;
    case "model_call":
      setState("thinking…");
      thinking = null;
      break;
    case "thinking_delta":
      thinking = thinking || chatItem(el("div", "msg thinking", ""));
      thinking.textContent += e.text;
      break;
    case "text_delta": {
      stream = stream || agentBubble();
      stream.box.classList.add("streaming");
      stream.text += e.text;
      const target = stream;
      if (!target.pending) {
        target.pending = true;
        requestAnimationFrame(() => {
          target.pending = false;
          const follow = nearBottom(chat);
          target.body.innerHTML = md(target.text);
          if (follow) chat.scrollTop = chat.scrollHeight;
        });
      }
      setState("writing…");
      break;
    }
    case "model_reply":
      if (stream) { stream.box.classList.remove("streaming"); lastStreamed = stream; }
      stream = null;
      thinking = null;
      logLine("dim", `reply: ${e.input_tokens.toLocaleString()} in · ${e.output_tokens.toLocaleString()} out`, live);
      break;
    case "answer": {
      const target = lastStreamed && lastStreamed.text.trim() === e.text.trim() ? lastStreamed : agentBubble();
      target.text = e.text;
      target.body.innerHTML = md(e.markdown || e.text);
      lastStreamed = null;
      if (request) {
        const id = request.node.id + "-answer";
        if (!graph.byId.has(id)) { graph.add(id, "answer", "answer", request.node.id, short(e.text, 200)); request.nodes.push(id); }
      }
      break;
    }
    case "usage":
      if (request && request.els.length) request.els[request.els.length - 1].appendChild(el("div", "usage", e.text));
      logLine("dim", e.text, live);
      break;
    case "tool_call":
      toolCall(e, live);
      break;
    case "tool_result":
      toolResult(e, live);
      break;
    case "tool_denied":
    case "tool_refused":
      notRun(e, live);
      break;
    case "todos":
      todos(e.items);
      break;
    case "task":
      termLine(/exit code 0/.test(e.text) ? "ok" : "warn", `background task ${e.id} ended: ${e.text}  [${short(e.command, 60)}]`, live);
      logLine("dim", `task ${e.id}: ${e.text}`, live);
      refreshState();
      break;
    case "subagent": {
      if (e.what === "start") {
        const parent = [...calls.entries()].reverse().find(([, c]) => c.name === "delegate");
        agents += 1;
        currentAgent = graph.add("agent-" + agents, "agent", e.name, parent ? parent[0] : request && request.node.id, `${e.name}: ${e.info}`);
        if (request) request.nodes.push(currentAgent.id);
        chatItem(el("div", "sub", `↳ ${e.name}: ${short(String(e.info), 140)}`));
        logLine("tool", `↳ ${e.name} started`, live);
      } else if (e.what === "tool_call") {
        const [, subject] = subjectOf(e.info.args || {});
        graph.add("sub-" + e.info.id + "-" + graph.nodes.length, "tool", e.info.name, currentAgent && currentAgent.id, `${e.info.name} ${subject}`);
        logLine("dim", `  · ${e.name} → ${e.info.name} ${short(subject, 50)}`, live);
      } else {
        if (currentAgent) graph.setStatus(currentAgent.id, e.info.stop === "completed" ? "ok" : "error");
        for (const n of graph.nodes) if (n.id.startsWith("sub-") && n.status === "running") graph.setStatus(n.id, "ok");
        chatItem(el("div", "sub", `↳ ${e.name} finished: ${e.info.calls} tool calls, ~${e.info.tokens.toLocaleString()} tokens, ${Math.round(e.info.seconds)} s`));
        currentAgent = null;
      }
      break;
    }
    case "rolled_back":
      if (request) {
        request.els.forEach((x) => x.classList.add("rolled"));
        graph.stale(request.nodes);
        for (const id of request.nodes) if (graph.byId.get(id) && graph.byId.get(id).status === "running") graph.setStatus(id, "denied");
      }
      logLine("warn", "request removed from the conversation", live);
      break;
    case "note":
      logLine("dim", e.text, live);
      termLine("warn", e.text, live);
      break;
    case "info":
    case "warn":
    case "error":
      system(e.type, e.text);
      logLine(e.type === "info" ? "dim" : e.type === "warn" ? "warn" : "bad", short(e.text.split("\n")[0], 90), live);
      termLine(e.type === "info" ? "out" : e.type === "warn" ? "warn" : "bad", e.type === "info" ? short(e.text.split("\n")[0], 160) : e.text, live);
      break;
  }
}

// --- the side panels ------------------------------------------------------------------------------------------------------------
function meter(tokens, window, level) {
  const pct = window ? Math.min(100, Math.round((100 * tokens) / window)) : 0;
  $("meter-fill").style.width = pct + "%";
  $("meter-fill").parentElement.className = "meter " + (level === "critical" || level === "full" ? "full" : level === "warn" ? "warn" : "");
  $("context").textContent = `${(tokens / 1000).toFixed(1)}k / ${(window / 1000).toFixed(1)}k`;
}
function status(s) {
  $("model").textContent = s.model;
  $("model").title = `${s.provider} · ${s.model}`;
  $("workspace").textContent = s.workspace;
  $("mode").value = s.mode;
  $("cost").textContent = s.cost === null ? "unknown" : s.cost === 0 ? "free" : "$" + s.cost.toFixed(4);
  $("turns").textContent = s.turns;
  meter(s.context_tokens, s.context_window, s.context_tokens > 0.9 * s.context_window ? "critical" : s.context_tokens > 0.7 * s.context_window ? "warn" : "ok");
}
function todos(items) {
  const box = $("todos");
  box.replaceChildren();
  const done = items.filter((t) => t.status === "completed").length;
  $("todo-count").textContent = items.length ? `${done}/${items.length} done` : "";
  for (const t of items) {
    const row = box.appendChild(el("div", "todo " + t.status));
    row.append(el("span", "mark", { completed: "●", in_progress: "◐" }[t.status] || "○"), el("span", "what", t.content));
    row.appendChild(el("span", "bar")).appendChild(el("i"));
  }
  if (!items.length) box.appendChild(el("div", "queue-empty", "no todo list: the agent writes one for a job with several parts"));
}
function tasks(list) {
  const box = $("tasks");
  box.replaceChildren();
  for (const t of list) box.appendChild(el("div", "bg-task" + (t.running ? " running" : ""), `${t.running ? "⟳" : "■"} ${t.id} · ${short(t.command, 40)} · ${t.text}`));
}
async function refreshState() {
  const s = await api("/api/state");
  status(s.status);
  tasks(s.tasks);
}

// --- explorer and file viewer ---------------------------------------------------------------------------------------------------
const expanded = new Set([""]);
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return r.json();
}
async function folder(path, depth, box) {
  const r = await api("/api/files?path=" + encodeURIComponent(path));
  if (r.error) { box.appendChild(el("div", "empty", r.error)); return; }
  if (!r.entries.length) box.appendChild(el("div", "empty", "(empty)"));
  for (const entry of r.entries) {
    const row = box.appendChild(el("div", "row " + (entry.dir ? "dir" : "file")));
    row.style.paddingLeft = 10 + depth * 14 + "px";
    const open = expanded.has(entry.path);
    row.append(el("span", "chev", entry.dir ? (open ? "▾" : "▸") : ""), el("span", "icon", entry.dir ? "▣" : "▢"), el("span", "name", entry.name));
    if (changed.has(entry.path)) row.appendChild(el("span", "badge", "M"));
    if (entry.path === $("file-tab").dataset.path) row.classList.add("open-file");
    const children = box.appendChild(el("div"));
    if (entry.dir) {
      row.addEventListener("click", () => {
        if (expanded.has(entry.path)) { expanded.delete(entry.path); children.replaceChildren(); row.firstChild.textContent = "▸"; }
        else { expanded.add(entry.path); row.firstChild.textContent = "▾"; folder(entry.path, depth + 1, children); }
      });
      if (open) await folder(entry.path, depth + 1, children);
    } else {
      row.addEventListener("click", () => openFile(entry.path));
    }
  }
}
let treeTimer = null;
function refreshTree() {
  clearTimeout(treeTimer);
  treeTimer = setTimeout(async () => {
    const box = el("div");
    await folder("", 0, box);
    $("tree").replaceChildren(...box.childNodes);
  }, 150);
}
async function openFile(path, focus = true) {
  const r = await api("/api/file?path=" + encodeURIComponent(path));
  const tab = $("file-tab");
  tab.dataset.path = path;
  tab.textContent = "File · " + path.split("/").pop();
  $("file-head").textContent = r.error ? r.error : r.path + (r.truncated ? "  (the first 200 KB)" : "") + (changed.has(path) ? "  · changed by the agent" : "");
  const body = r.text === undefined ? (r.binary ? "(a binary file: not shown)" : "") : r.text;
  $("gutter").textContent = r.text === undefined ? "" : body.split("\n").map((_, i) => i + 1).join("\n");
  $("code").innerHTML = r.text === undefined ? esc(body) : highlight(body, path.includes(".") ? path.split(".").pop() : "");
  if (focus) selectTab("file");
  refreshTree();
}
function selectTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === name));
  $("chat").classList.toggle("hidden", name !== "chat");
  $("file").classList.toggle("hidden", name !== "file");
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => selectTab(t.dataset.tab)));
graph.onClick = (n) => {
  const call = calls.get(n.id);
  if (!call) return;
  selectTab("chat");
  call.result.classList.remove("hidden");
  call.box.scrollIntoView({ block: "center", behavior: "smooth" });
};
document.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", () => {
  b.classList.toggle("on");
  $("app").classList.toggle("no-" + b.dataset.toggle, !b.classList.contains("on"));
  graph.kick();
}));

// --- sending ------------------------------------------------------------------------------------------------------------------
async function send(words) {
  const r = await api("/api/send", { text: words });
  if (!r.ok) system("warn", r.error);
  return r.ok;
}
$("composer").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const words = text.value.trim();
  if (words && !busy && (await send(words))) text.value = "";
});
text.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); $("send").click(); }
});
$("stop").addEventListener("click", () => api("/api/stop", {}));
$("mode").addEventListener("change", (ev) => send("/mode " + ev.target.value));

// --- start: what happened so far, then the live stream ------------------------------------------------------------------------------
(async () => {
  const state = await api("/api/state");
  for (const e of state.messages) show(e, false);
  lastStreamed = null;
  show({ type: "busy", busy: state.status.busy, status: state.status }, false);
  todos(state.todos);
  tasks(state.tasks);
  refreshTree();
  const events = new EventSource("/events?after=" + state.last_event);     // reconnects by itself, with Last-Event-ID
  events.onmessage = (m) => show(JSON.parse(m.data));
  events.onopen = () => { $("conn").textContent = "live"; $("conn").className = "conn live"; refreshState(); };
  events.onerror = () => { $("conn").textContent = "reconnecting"; $("conn").className = "conn"; };
})();
