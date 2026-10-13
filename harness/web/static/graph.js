// Lesson 60: the run graph. The force layout of Lesson 54 kept moving (every new node pushed the others), its labels piled up, and its
// view glided off the panel. Here a node's place is worked out once, when it is added, and never changes:
//   - requests sit on a timeline, left to right, each far enough from the last to clear its rings;
//   - a request's tool calls, sub-agents and answer take numbered slots on rings around it (8 on the first, 16 on the second ...),
//     skipping the slot straight below, where the request's own label goes, and any slot whose dot would cover something already
//     placed; a sub-agent's calls ring the sub-agent;
//   - a label points away from its request, and is hidden (the tooltip keeps it) when it would overlap a label or a node already placed.
// RunLayout is pure (tests/test_web_page.py runs it in Node); Graph draws it in SVG, with Follow (the newest request, never smaller than
// readable), Fit (everything) and wheel-zoom / drag-pan.
"use strict";
const SVG_NS = "http://www.w3.org/2000/svg";
const RADIUS = { request: 9, agent: 7, tool: 5, answer: 4 };
const RINGS = { request: [64, 46], agent: [34, 26] };          // first ring's radius, then the gap between rings
const REQUEST_GAP = 60, LABEL_ROOM = 70, CHAR_W = 6.1, LABEL_H = 12, LABEL_CHARS = 14, MAX_NODES = 400, FOLLOW_MIN = 0.85;

const shorten = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const overlap = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;

class RunLayout {
  constructor() {
    this.nodes = new Map();
    this.boxes = [];               // what a new label must not cover: placed labels and nodes
    this.last = null;              // the newest request
    this.bounds = { x0: 0, y0: 0, x1: 0, y1: 0 };
  }

  slot(hub) {
    // the next free slot on the rings around `hub`: [x, y, angle]
    const [first, gap] = RINGS[hub.kind] || RINGS.agent;
    let index = hub.used++;
    for (let ring = 1; ; ring++) {
      const count = 8 * ring, offset = ring % 2 ? 0 : Math.PI / count;
      const angles = [];
      for (let i = 0; i < count; i++) {
        const a = -Math.PI / 2 + offset + (2 * Math.PI * i) / count;
        if (hub.kind === "request" && Math.abs(Math.atan2(Math.sin(a - Math.PI / 2), Math.cos(a - Math.PI / 2))) < 0.3) continue;  // below: the label's
        angles.push(a);
      }
      if (index < angles.length) {
        const r = first + (ring - 1) * gap, a = angles[index];
        return [hub.x + r * Math.cos(a), hub.y + r * Math.sin(a), a, r];
      }
      index -= angles.length;
    }
  }

  place(box) {
    // keep a label only if it covers nothing placed so far
    if (this.boxes.some((b) => overlap(b, box))) return false;
    this.boxes.push(box);
    return true;
  }

  grow(b) {
    const B = this.bounds;
    B.x0 = Math.min(B.x0, b.x0); B.y0 = Math.min(B.y0, b.y0); B.x1 = Math.max(B.x1, b.x1); B.y1 = Math.max(B.y1, b.y1);
  }

  add(id, kind, label, parentId) {
    const parent = parentId ? this.nodes.get(parentId) : null;
    const text = shorten(label || "", LABEL_CHARS);
    let node;
    if (kind === "request" || !parent) {
      const prev = this.last;
      const x = prev ? prev.x + prev.reach + RINGS.request[0] + LABEL_ROOM + REQUEST_GAP : 0;
      node = { id, kind, x, y: 0, used: 0, reach: RINGS.request[0], hub: null };
      node.label = { x, y: 24, anchor: "middle", text };
      if (kind === "request") this.last = node;
    } else {
      // a sub-agent sits on its request's rings (its parent is the delegate call); everything else rings its parent's hub
      const hub = kind === "agent" ? parent.hub || parent : parent.kind === "tool" ? parent.hub || parent : parent;
      const R = RADIUS[kind] || 5;
      let x, y, a, r;
      for (let tries = 0; tries < 64; tries++) {   // skip a slot whose dot would cover a label or a dot already placed (a sub-agent's ring
        [x, y, a, r] = this.slot(hub);              // reaches into its request's)
        const dot = { x0: x - R - 2, y0: y - R - 2, x1: x + R + 2, y1: y + R + 2 };
        if (!this.boxes.some((b) => overlap(b, dot))) break;
      }
      node = { id, kind, x, y, used: 0, reach: 0, hub };
      for (let h = hub; h; h = h.hub) h.reach = Math.max(h.reach, Math.hypot(x - h.x, y - h.y) + (kind === "agent" ? RINGS.agent[0] + RINGS.agent[1] : 0));
      const c = Math.cos(a), s = Math.sin(a), d = RADIUS[kind] + 5;
      const anchor = c > 0.35 ? "start" : c < -0.35 ? "end" : "middle";
      node.label = { x: x + c * d, y: anchor === "middle" ? (s < 0 ? y - d - 2 : y + d + 9) : y + 3.5, anchor, text, r };
    }
    const R = RADIUS[kind] || 5;
    const dot = { x0: node.x - R, y0: node.y - R, x1: node.x + R, y1: node.y + R };
    this.boxes.push(dot);
    this.grow(dot);
    const L = node.label, w = L.text.length * CHAR_W;
    const x0 = L.anchor === "start" ? L.x : L.anchor === "end" ? L.x - w : L.x - w / 2;
    const box = { x0, y0: L.y - LABEL_H + 2, x1: x0 + w, y1: L.y + 3 };
    if (!L.text || !this.place(box)) node.label = null;
    else { L.box = box; this.grow(box); }
    this.nodes.set(id, node);
    return node;
  }
}

function makeLayout() {
  return new RunLayout();
}

class Graph {
  constructor(svg, panel) {
    this.svg = svg;
    this.links = svg.appendChild(document.createElementNS(SVG_NS, "g"));
    this.dots = svg.appendChild(document.createElementNS(SVG_NS, "g"));
    this.nodes = [];
    this.byId = new Map();
    this.layout = new RunLayout();
    this.mode = "follow";                       // follow | fit | free
    this.view = { cx: 0, cy: 0, scale: 1 };
    let drag = null;
    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const p = this.point(ev);
      const factor = ev.deltaY < 0 ? 1.15 : 1 / 1.15;
      const v = this.view, scale = Math.min(3, Math.max(0.1, v.scale * factor));
      v.cx = p.x - (p.x - v.cx) * (v.scale / scale);   // zoom about the cursor
      v.cy = p.y - (p.y - v.cy) * (v.scale / scale);
      v.scale = scale;
      this.setMode("free");
    }, { passive: false });
    svg.addEventListener("pointerdown", (ev) => { if (ev.target === svg) { drag = { x: ev.clientX, y: ev.clientY }; svg.setPointerCapture(ev.pointerId); } });
    svg.addEventListener("pointermove", (ev) => {
      if (!drag) return;
      this.view.cx -= (ev.clientX - drag.x) / this.view.scale;
      this.view.cy -= (ev.clientY - drag.y) / this.view.scale;
      drag = { x: ev.clientX, y: ev.clientY };
      this.setMode("free");
    });
    svg.addEventListener("pointerup", () => { drag = null; });
    if (window.ResizeObserver) new ResizeObserver(() => this.draw()).observe(svg);
    this.panel = panel;
  }
  point(ev) {
    const box = this.svg.getBoundingClientRect(), v = this.view;
    return { x: v.cx + (ev.clientX - box.left - box.width / 2) / v.scale, y: v.cy + (ev.clientY - box.top - box.height / 2) / v.scale };
  }
  setMode(mode) {
    this.mode = mode;
    if (this.panel) this.panel.querySelectorAll("[data-graph]").forEach((b) => b.classList.toggle("on", b.dataset.graph === mode));
    this.draw();
  }
  add(id, kind, label, parentId, title) {
    if (this.byId.has(id)) return this.byId.get(id);
    const p = this.layout.add(id, kind, label, parentId);
    const n = { id, kind, x: p.x, y: p.y, status: "ok", g: document.createElementNS(SVG_NS, "g") };
    n.g.setAttribute("transform", `translate(${p.x.toFixed(1)},${p.y.toFixed(1)})`);
    const circle = document.createElementNS(SVG_NS, "circle");
    circle.setAttribute("r", RADIUS[kind] || 5);
    const tip = document.createElementNS(SVG_NS, "title");
    tip.textContent = title || label;
    n.g.append(circle, tip);
    if (p.label) {
      const t = document.createElementNS(SVG_NS, "text");
      t.setAttribute("x", (p.label.x - p.x).toFixed(1));
      t.setAttribute("y", (p.label.y - p.y).toFixed(1));
      t.setAttribute("text-anchor", p.label.anchor);
      t.textContent = p.label.text;
      n.g.appendChild(t);
    }
    n.g.addEventListener("click", () => this.onClick && this.onClick(n));
    const parent = parentId && this.byId.get(parentId);
    if (parent) {
      const line = document.createElementNS(SVG_NS, "line");
      line.setAttribute("x1", parent.x); line.setAttribute("y1", parent.y); line.setAttribute("x2", p.x); line.setAttribute("y2", p.y);
      if (kind === "request") line.setAttribute("class", "chain");
      this.links.appendChild(line);
      n.line = line;
    }
    this.dots.appendChild(n.g);
    this.nodes.push(n);
    this.byId.set(id, n);
    this.setStatus(id, kind === "tool" || kind === "agent" ? "running" : "ok");
    if (this.nodes.length > MAX_NODES) this.clearOldest();
    $("graph-count").textContent = this.nodes.length + " nodes";
    this.draw();
    return n;
  }
  clearOldest() {
    const old = this.nodes.shift();
    old.g.remove();
    if (old.line) old.line.remove();
    this.byId.delete(old.id);
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
    this.nodes.forEach((n) => { n.g.remove(); if (n.line) n.line.remove(); });
    this.nodes = [];
    this.byId.clear();
    this.layout = new RunLayout();
    $("graph-count").textContent = "";
    this.setMode("follow");
  }
  draw() {
    const box = this.svg.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const v = this.view, B = this.layout.bounds, pad = 30;
    if (this.mode === "fit" && this.nodes.length) {
      v.cx = (B.x0 + B.x1) / 2; v.cy = (B.y0 + B.y1) / 2;
      v.scale = Math.min(1.5, box.width / (B.x1 - B.x0 + 2 * pad), box.height / (B.y1 - B.y0 + 2 * pad));
    } else if (this.mode === "follow") {
      const last = this.layout.last, reach = last ? last.reach + LABEL_ROOM : 100;
      v.cx = last ? last.x : 0; v.cy = 0;
      // the newest request and its rings, but never too small to read (labels 8.5 px or more): in a narrow panel the outer ring of a big
      // request goes past the edge, and Fit shows it
      v.scale = Math.max(FOLLOW_MIN, Math.min(1, box.width / (2 * reach + pad), box.height / (2 * reach + pad)));
    }
    const w = box.width / v.scale, h = box.height / v.scale;
    this.svg.setAttribute("viewBox", `${(v.cx - w / 2).toFixed(1)} ${(v.cy - h / 2).toFixed(1)} ${w.toFixed(1)} ${h.toFixed(1)}`);
    this.svg.classList.toggle("small", v.scale < 0.55);          // too small to read: labels hide, tooltips stay
  }
}
