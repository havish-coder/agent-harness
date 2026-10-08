// Lesson 53: the smallest page that drives the agent. The conversation so far comes from /api/state,
// then /events streams what happens next. Text goes in with textContent only: nothing the model writes is HTML.
const log = document.getElementById("log"), text = document.getElementById("text");
const sendButton = document.getElementById("send"), stopButton = document.getElementById("stop");
let answer = null;          // the element the streamed answer is being written into
let streamed = null;        // the last reply that was streamed: the final answer is usually the same text

function line(kind, words) {
  const div = document.createElement("div");
  div.className = "line " + kind;
  div.textContent = words;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function show(e) {
  if (e.type === "text_delta") {
    answer = answer || line("answer", "");
    answer.textContent += e.text;
    log.scrollTop = log.scrollHeight;
  } else if (e.type === "answer") {
    if (!(streamed && streamed.textContent.trim() === e.text.trim())) line("answer", e.text);
    streamed = null;
  } else if (e.type === "model_reply") {
    streamed = answer;        // the next text is a new reply
    answer = null;
  } else if (e.type === "user") {
    line("user", "you> " + e.text);
  } else if (e.type === "tool_call") {
    line("tool_call", "● " + e.name + "(" + JSON.stringify(e.args) + ")");
  } else if (e.type === "tool_result") {
    line("tool_result", "  └ " + e.text.split("\n").slice(0, 4).join("\n    "));
  } else if (e.type === "tool_denied" || e.type === "tool_refused") {
    line("warn", "  └ not run: " + e.reason);
  } else if (e.type === "busy") {
    sendButton.disabled = e.busy;
    stopButton.disabled = !e.busy;
    if (e.status) status(e.status);
  } else if (["info", "warn", "error", "note", "usage"].includes(e.type)) {
    line(e.type, e.text);
  }
}

function status(s) {
  document.getElementById("status").textContent =
    `${s.model} · context ~${s.context_tokens}/${s.context_window} · mode ${s.mode}` + (s.busy ? " · working…" : "");
}

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return r.json();
}

document.getElementById("composer").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const words = text.value.trim();
  if (!words) return;
  const r = await post("/api/send", { text: words });
  if (r.ok) text.value = ""; else line("warn", r.error);
});
text.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendButton.click(); }
});
stopButton.addEventListener("click", () => post("/api/stop", {}));

(async () => {
  const state = await (await fetch("/api/state")).json();
  state.messages.forEach(show);
  answer = null;
  show({ type: "busy", busy: state.status.busy, status: state.status });
  // EventSource reconnects by itself and sends Last-Event-ID, so a dropped connection loses nothing.
  const events = new EventSource("/events?after=" + state.last_event);
  events.onmessage = (m) => show(JSON.parse(m.data));
  events.onopen = async () => status((await (await fetch("/api/state")).json()).status);
  events.onerror = () => document.getElementById("status").textContent = "reconnecting…";
})();
