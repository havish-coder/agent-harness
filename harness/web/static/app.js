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
  clear() {
    this.nodes.forEach((n) => n.g.remove());
    this.edges.forEach((e) => e.line.remove());
    this.nodes = [];
    this.edges = [];
    this.byId.clear();
    $("graph-count").textContent = "";
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

// --- questions from the agent (Lesson 55): an approval, a choice, or text; the first page to answer wins ---------------------------
const cards = new Map();           // question id -> {card, payload}
const RISKY = /^(deletes|rewrites|overwrites|runs as administrator)/;
function diffView(text) {
  const pre = el("pre", "diff");
  for (const line of text.split("\n")) {
    const cls = /^(\+\+\+|---|new file)/.test(line) ? "head" : line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
    pre.appendChild(el("span", cls, line + "\n"));
  }
  return pre;
}
function choiceButton(box, label, cls, id, value) {
  const b = box.appendChild(el("button", "btn " + cls, label));
  b.type = "button";
  b.addEventListener("click", async () => {
    const r = await api("/api/answer", { id, answer: typeof value === "function" ? value() : value });
    if (r.error) system("warn", r.error);
  });
  return b;
}
function question(e) {
  if (cards.has(e.id)) return;
  const card = el("div", "ask " + e.kind), title = card.appendChild(el("div", "ask-title")), buttons = el("div", "ask-buttons");
  if (e.kind === "approval") {
    title.append(el("span", "q", "?"), el("b", "", e.tool), document.createTextNode(" wants to run"));
    if (e.destructive) title.appendChild(el("span", "danger", "  may destroy data"));
    if (e.reason) card.appendChild(el("div", "ask-reason", "asking because " + e.reason));
    for (const note of e.notes) card.appendChild(el("div", "ask-note" + (RISKY.test(note) ? " danger" : ""), "! " + note));
    if (e.tool === "run_shell" && typeof e.args.command === "string") card.appendChild(el("pre", "ask-command", e.args.command));
    if (e.preview) card.appendChild(diffView(e.preview));
    else if (e.tool !== "run_shell") card.appendChild(el("pre", "ask-args", JSON.stringify(e.args, null, 2)));
    choiceButton(buttons, "Yes", "yes", e.id, "yes");
    choiceButton(buttons, "No", "no", e.id, "no");
    if (e.always) choiceButton(buttons, `Always allow ${e.always} (this session)`, "always", e.id, "always");
    graph.setStatus(e.call_id, "waiting");
    const call = calls.get(e.call_id);
    if (call) call.box.className = "call waiting";
  } else if (e.kind === "choice") {
    title.textContent = e.question;
    for (const [key, label] of Object.entries(e.options)) choiceButton(buttons, label, "option", e.id, key);
  } else {
    title.textContent = e.question;
    const input = card.appendChild(el("textarea", "ask-input"));
    input.rows = 2;
    choiceButton(buttons, "Answer", "yes", e.id, () => input.value);
    choiceButton(buttons, "Skip", "no", e.id, "");
  }
  card.appendChild(buttons);
  chatItem(card);
  card.scrollIntoView({ block: "nearest" });
  cards.set(e.id, { card, payload: e });
  setState("waiting for you");
  $("busy-chip").textContent = "waiting for you";
  document.title = "● Agent Harness: waiting for you";
}
function answered(e) {
  const found = cards.get(e.id);
  document.title = "Agent Harness";
  if (!found) return;
  const { card, payload } = found;
  card.classList.add("done");
  card.querySelectorAll("button, textarea").forEach((b) => (b.disabled = true));
  const said = payload.kind === "choice" ? payload.options[e.answer] || "no answer" : payload.kind === "text" ? (e.answer ? "answered" : "no answer") : e.answer;
  card.appendChild(el("div", "ask-answer", "→ " + said));
  if (payload.kind === "approval" && e.answer !== "no") {
    graph.setStatus(payload.call_id, "running");
    const call = calls.get(payload.call_id);
    if (call) call.box.className = "call running";
  }
  setState(busy ? "thinking…" : "idle");
  $("busy-chip").textContent = busy ? "working" : "idle";
  logLine(e.answer === "no" ? "warn" : "dim", `you answered: ${said}`, true);
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
      if (!busy && live) {
        currentAgent = stream = thinking = null;
        refreshState();                      // the chat's title, the background tasks
        if (!$("journal").classList.contains("hidden")) journal();
      }
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
    case "question":
      question(e);
      break;
    case "answered":
      answered(e);
      break;
    case "plan": {
      const card = el("div", "ask plan");
      card.appendChild(el("div", "ask-title", "Proposed plan"));
      card.appendChild(el("div", "md")).innerHTML = md(e.markdown || e.text);
      chatItem(card);
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
  $("chat-title").textContent = s.chat ? s.chat.title || "untitled" : "new";
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
    else if (entry.dir && [...changed].some((p) => p.startsWith(entry.path + "/"))) row.appendChild(el("span", "badge", "•"));
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
  for (const tab of ["chat", "file", "journal"]) $(tab).classList.toggle("hidden", name !== tab);
  if (name === "journal") journal();
}

// --- the progress journal, chats and projects, settings (Lesson 56) ------------------------------------------------------------------
function button(box, label, cls, onClick) {
  const b = box.appendChild(el("button", "btn " + cls, label));
  b.type = "button";
  b.disabled = busy;
  b.addEventListener("click", onClick);
  return b;
}
async function journal() {
  const j = await api("/api/journal"), box = $("journal");
  box.replaceChildren();
  const state = j.mode === "off" ? "off" : j.active ? "on" : "not started";
  box.appendChild(el("div", "journal-head", `progress journal: ${state}` + (j.updated ? ` · updated ${j.updated} by ${j.by || "?"}` : "")));
  const actions = box.appendChild(el("div", "row-buttons"));
  if (!j.active) button(actions, "Start", "yes", () => send("/progress start"));
  if (j.active) button(actions, "Update now", "option", () => send("/progress update"));
  if (j.active) button(actions, "Stop", "no", () => send("/progress stop"));
  if (j.tainted) box.appendChild(el("div", "sys warn", "written after content you may not trust was read: it is read as information, not instructions (/progress trust once you have checked it)"));
  box.appendChild(el("div", "md")).innerHTML = j.exists ? md(j.body) :
    md("No journal in this project yet. **Start** keeps one: every later chat, here or in the terminal, begins from where this one stopped.");
}

const drawer = { open: null };
async function openDrawer(name) {
  if (drawer.open === name) return closeDrawer();
  drawer.open = name;
  document.querySelectorAll("[data-drawer]").forEach((b) => b.classList.toggle("on", b.dataset.drawer === name));
  $("drawer").classList.remove("hidden");
  $("drawer-title").textContent = name === "chats" ? "Chats and projects" : "Settings";
  const body = $("drawer-body");
  body.replaceChildren(el("div", "small", "loading…"));
  const box = el("div");
  box.style.display = "contents";
  if (name === "chats") await chatsDrawer(box); else await settingsDrawer(box);
  body.replaceChildren(box);
}
function closeDrawer() {
  drawer.open = null;
  $("drawer").classList.add("hidden");
  document.querySelectorAll("[data-drawer]").forEach((b) => b.classList.remove("on"));
}
function pick(box, title, detail, current, onClick) {
  const b = box.appendChild(el("button", "pick" + (current ? " current" : "")));
  b.type = "button";
  b.append(el("span", "", title), el("span", "small", detail));
  b.disabled = current || busy;
  b.addEventListener("click", async () => { closeDrawer(); await onClick(); });
}
async function chatsDrawer(box) {
  const c = await api("/api/chats");
  box.appendChild(el("h3", "", "Chats in this project"));
  const actions = box.appendChild(el("div", "row-buttons"));
  button(actions, "+ New chat", "yes", () => { closeDrawer(); send("/reset"); });
  if (c.current) {
    const name = el("input");
    name.placeholder = "a name for this chat";
    const field = box.appendChild(el("div", "field"));
    field.appendChild(name);
    button(actions, "Rename", "option", () => name.value.trim() && (closeDrawer(), send("/rename " + name.value.trim())));
  }
  if (!c.saving) box.appendChild(el("div", "hint", "chats aren't being saved (save_chats is off, or --no-save)"));
  for (const chat of c.chats) pick(box, chat.title, `${chat.age} · ${chat.messages} messages · ${chat.model}`, chat.id === c.current, () => send("/resume " + chat.id));
  if (c.saving && !c.chats.length) box.appendChild(el("div", "hint", "no saved chats yet: your first message starts one"));
  box.appendChild(el("h3", "", "Projects"));
  for (const p of c.projects) pick(box, p.name || p.path, p.path, p.current, async () => {
    const r = await api("/api/project", { path: p.path });
    if (r.error) system("warn", r.error);
  });
  box.appendChild(el("div", "hint", "A project is a folder the agent has worked in. To add one: harness --web --workspace FOLDER"));
}
async function settingsDrawer(box) {
  const s = await api("/api/settings");
  box.appendChild(el("h3", "", "Connect your LLM"));
  const provider = el("select"), model = el("input"), url = el("input"), key = el("div");
  for (const p of s.providers) provider.appendChild(new Option(p.name, p.name, false, p.name === s.provider));
  model.value = s.model;
  model.setAttribute("list", "models");
  const list = box.appendChild(el("datalist"));
  list.id = "models";
  for (const m of s.models) list.appendChild(new Option(m, m));
  url.value = s.base_url;
  url.placeholder = "the provider's own address";
  const showKey = () => {
    const p = s.providers.find((x) => x.name === provider.value);
    key.className = !p.key ? "hint" : p.key_set ? "key-ok" : "key-missing";
    key.textContent = !p.key ? "no API key needed" : p.key_set ? `✓ ${p.key} is set` :
      `✗ ${p.key} is not set: set it in your environment (or a .env file) and start the server again. Keys are never typed here.`;
  };
  provider.addEventListener("change", showKey);
  showKey();
  for (const [label, input] of [["Provider", provider], ["Model", model], ["Address (optional)", url]]) {
    const field = box.appendChild(el("div", "field"));
    field.append(el("span", "label", label), input);
  }
  box.appendChild(key);
  const actions = box.appendChild(el("div", "row-buttons"));
  button(actions, "Connect", "yes", async () => {
    closeDrawer();
    const r = await api("/api/connect", { provider: provider.value, model: model.value, base_url: url.value });
    if (r.error) system("warn", r.error);
  });
  box.appendChild(el("div", "hint", "The chat carries on with the new model. Background commands and MCP servers are restarted."));
  box.appendChild(el("h3", "", "Output style"));
  const style = el("select");
  for (const name of s.styles) style.appendChild(new Option(name, name, false, name === s.style));
  style.addEventListener("change", () => send("/style " + style.value));
  box.appendChild(style).classList.add("pill");
  box.appendChild(el("h3", "", "Settings in effect"));
  box.appendChild(el("pre", "", s.config));
  box.appendChild(el("div", "hint", "Change them in ~/.harness/settings.json or the project's .harness/settings.json, then start the server again."));
}
document.querySelectorAll("[data-drawer]").forEach((b) => b.addEventListener("click", () => openDrawer(b.dataset.drawer)));
$("drawer-close").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && drawer.open) closeDrawer(); });
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
  if (words && busy) {                      // one request at a time: say so instead of doing nothing (seen live, Lesson 55)
    const box = $("composer");
    box.classList.remove("nudge");
    void box.offsetWidth;                   // restart the animation
    box.classList.add("nudge");
    setState("still working: wait for it, or press ■ to stop");
  } else if (words && (await send(words))) {
    text.value = "";
  }
});
text.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); $("composer").requestSubmit(); }
});
$("stop").addEventListener("click", () => api("/api/stop", {}));
$("mode").addEventListener("change", (ev) => send("/mode " + ev.target.value));

// --- start: what happened so far, then the live stream ------------------------------------------------------------------------------
let loading = false, queued = [];
async function load() {
  loading = true;
  const state = await api("/api/state");
  for (const e of state.messages) show(e, false);
  lastStreamed = null;
  show({ type: "busy", busy: state.status.busy, status: state.status }, false);
  if (state.question) show(state.question, false);           // the agent was already waiting when this page opened
  todos(state.todos);
  tasks(state.tasks);
  $("chat-title").textContent = state.chat ? state.chat.title || "untitled" : "new";
  refreshTree();
  loading = false;
  for (const [id, e] of queued) if (id > state.last_event) show(e);      // what arrived while the state was on its way
  queued = [];
  return state;
}
async function redraw() {
  // another chat, another project, or a conversation cut short (/rewind, /compact): draw it again from the state (Lesson 56)
  const said = request ? request.els.filter((x) => x.classList.contains("sys")) : [];   // what the command said ("resumed: ...") stays
  chat.replaceChildren();
  graph.clear();
  calls.clear();
  cards.clear();
  changed.clear();
  request = stream = lastStreamed = thinking = null;
  await load();
  said.forEach((x) => append(chat, x));
  if (!$("journal").classList.contains("hidden")) journal();
}
(async () => {
  const state = await load();
  const events = new EventSource("/events?after=" + state.last_event);     // reconnects by itself, with Last-Event-ID
  events.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (loading) queued.push([+m.lastEventId, e]);
    else if (e.type === "conversation") redraw();
    else show(e);
  };
  events.onopen = () => { $("conn").textContent = "live"; $("conn").className = "conn live"; refreshState(); };
  events.onerror = () => { $("conn").textContent = "reconnecting"; $("conn").className = "conn"; };
})();
