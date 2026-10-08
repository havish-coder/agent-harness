"""Lesson 53 lab: what the web server adds between the agent and the page.

    python scripts/web_lab.py latency      # publish -> page, per event, with 1 and 5 pages open (scripted model)
    python scripts/web_lab.py throughput   # events per second through one stream
    python scripts/web_lab.py live         # Ollama: time to the first word, terminal session vs. the page

The page is played by httpx reading /events, in the same process, so both ends use one clock.
"""
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.commands import load_commands  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.messages import Message, Reply, Usage  # noqa: E402
from harness.providers.base import TextDelta  # noqa: E402
from harness.session import Session  # noqa: E402
from harness.web.server import Hub, WebUI, start  # noqa: E402
from harness.workspace import Workspace  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
BASE = {"save_chats": False, "auto_memory": "off", "journal": "off", "file_history": False, "todo": False, "audit_log": False}


class Streamer:
    """Streams `n` pieces, `gap` seconds apart (a 4B model on this laptop writes about 10 pieces a second)."""
    model = "streamer"

    def __init__(self, n, gap):
        self.n, self.gap = n, gap

    def chat(self, messages, tools):
        raise NotImplementedError

    def stream(self, messages, tools):
        for _ in range(self.n):
            time.sleep(self.gap)
            yield TextDelta("word ")
        yield Reply(Message("assistant", "word " * self.n), "end", Usage(1, self.n))


def serve(root, provider=None, **settings):
    session = Session(Settings(**(BASE | settings)), Workspace(root), WebUI(Hub()), None, interface="web")
    if provider is not None:
        session.agent.provider = provider
    server = start(session, load_commands(Path(root)), port=0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server, session


def page(server):
    client = httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", timeout=None)
    client.get(server.url)
    return client


def read(client, after, stop, seen):
    """Read the stream; record (event id, time received) for each event, until `stop` matches one."""
    with client.stream("GET", f"/events?after={after}") as r:
        event_id = None
        for line in r.iter_lines():
            if line.startswith("id: "):
                event_id = int(line[4:])
            elif line.startswith("data: "):
                seen.append((event_id, time.perf_counter(), line))
                if stop(line):
                    return


def finished(line):
    return '"type": "busy", "busy": false' in line


def latency(pages=(1, 5), n=200, gap=0.01):
    for count in pages:
        with tempfile.TemporaryDirectory() as root:
            server, session = serve(root, Streamer(n, gap))
            published = {}
            hub, original = session.ui.hub, session.ui.hub.publish

            def stamped(event, hub=hub, original=original, published=published):
                now = time.perf_counter()                         # before the JSON is made: that is part of the cost
                original(event)
                published[hub.last] = now
            hub.publish = stamped
            readers, seen = [], [[] for _ in range(count)]
            after = hub.last
            for i in range(count):
                t = threading.Thread(target=read, args=(page(server), after, finished, seen[i]))
                t.start()
                readers.append(t)
            time.sleep(0.3)
            page(server).post("/api/send", json={"text": "go"})
            for t in readers:
                t.join(30)
            delays = sorted(1000 * (when - published[i]) for s in seen for i, when, line in s if '"text_delta"' in line and i in published)
            server.closing = True
            server.shutdown()
            print(f"{count} page(s): {len(delays)} text events, publish -> page: median {statistics.median(delays):.2f} ms, "
                  f"p95 {delays[int(0.95 * len(delays))]:.2f} ms, max {delays[-1]:.2f} ms")


def throughput(n=20000):
    with tempfile.TemporaryDirectory() as root:
        server, session = serve(root)
        hub, seen = session.ui.hub, []
        after = hub.last
        t = threading.Thread(target=read, args=(page(server), after, lambda line: f'"n": {n - 1}' in line, seen))
        t.start()
        time.sleep(0.3)
        started = time.perf_counter()
        for i in range(n):
            hub.publish({"type": "text_delta", "text": "word ", "n": i})
        t.join(60)
        took = time.perf_counter() - started
        server.closing = True
        server.shutdown()
        print(f"{len(seen):,} of {n:,} events in {took:.2f} s: {len(seen) / took:,.0f} events/s through one stream")


def live(runs=3, request="Say hello in five words."):
    """Time to the first piece of the answer: the agent called directly (as the terminal does) vs. through the server."""
    with tempfile.TemporaryDirectory() as root:
        direct = []
        for _ in range(runs + 1):                                # the first run loads the model: not counted
            first = []
            s = Session(Settings(**BASE), Workspace(root), WebUI(Hub()), None)
            s.agent.on_event = lambda kind, data, first=first: first.append(time.perf_counter()) if kind == "text_delta" else None
            started = time.perf_counter()
            s.agent.run(request)
            direct.append(1000 * (first[0] - started))
        server, session = serve(root)
        via = []
        for _ in range(runs):
            session.reset()
            seen, client = [], page(server)
            reader = threading.Thread(target=read, args=(client, session.ui.hub.last, finished, seen))
            reader.start()
            time.sleep(0.3)
            started = time.perf_counter()
            client.post("/api/send", json={"text": request})
            reader.join(120)
            via.append(1000 * (next(t for _, t, line in seen if '"text_delta"' in line) - started))
        server.closing = True
        server.shutdown()
        print(f"time to the first word, {runs} warm runs: direct {', '.join(f'{x:.0f}' for x in direct[1:])} ms; "
              f"through the page {', '.join(f'{x:.0f}' for x in via)} ms")


if __name__ == "__main__":
    {"latency": latency, "throughput": throughput, "live": live}[sys.argv[1] if len(sys.argv) > 1 else "latency"]()
