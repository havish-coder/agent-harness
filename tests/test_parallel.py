"""Lesson 14: safe calls run together; unsafe calls run alone; results keep the model's order."""
import threading
import time

from harness.agent import Agent
from harness.tools.base import tool
from tests.fakes import ScriptedProvider, call, calls, final

timeline: list[tuple[str, str, float]] = []   # (event, name, time)
lock = threading.Lock()


def mark(event, name):
    with lock:
        timeline.append((event, name, time.monotonic()))


@tool(read_only=True, concurrency_safe=True)
def slow_read(name: str, seconds: float = 0.3) -> str:
    """Read slowly."""
    mark("start", name)
    time.sleep(seconds)
    mark("end", name)
    return f"read {name}"


@tool(read_only=True)            # read-only but NOT declared concurrency-safe: runs alone
def cautious(name: str) -> str:
    """A read-only tool that never declared itself parallel-safe."""
    mark("start", name)
    time.sleep(0.1)
    mark("end", name)
    return f"cautious {name}"


def run(*tool_calls):
    timeline.clear()
    agent = Agent(ScriptedProvider([calls(*tool_calls), final("done")]), [slow_read, cautious], "s")
    start = time.monotonic()
    agent.run("go")
    return agent, time.monotonic() - start


def test_safe_calls_overlap_and_keep_their_order():
    agent, elapsed = run(*(call("slow_read", id=f"c{i}", name=f"f{i}", seconds=0.3) for i in range(4)))
    assert elapsed < 0.9                                   # 4 × 0.3 s would be 1.2 s serially
    starts = [t for e, _, t in timeline if e == "start"]
    ends = [t for e, _, t in timeline if e == "end"]
    assert max(starts) < min(ends)                         # all four were running at once
    results = [m for m in agent.messages if m.role == "tool"]
    assert [m.content for m in results] == ["read f0", "read f1", "read f2", "read f3"]
    assert [m.tool_call_id for m in results] == ["c0", "c1", "c2", "c3"]


def test_unsafe_call_splits_batches():
    agent = Agent(ScriptedProvider([]), [slow_read, cautious], "s")
    batches = agent.batches([call("slow_read", id="1", name="a"), call("slow_read", id="2", name="b"),
                             call("cautious", id="3", name="c"), call("slow_read", id="4", name="d"),
                             call("nope", id="5"), call("slow_read", id="6", name="e")])
    assert [[c.id for c in b] for b in batches] == [["1", "2"], ["3"], ["4"], ["5"], ["6"]]


def test_unsafe_call_runs_after_the_batch_before_it():
    run(call("slow_read", id="1", name="a", seconds=0.2), call("slow_read", id="2", name="b", seconds=0.2),
        call("cautious", id="3", name="c"))
    t = {(e, n): ts for e, n, ts in timeline}
    assert t[("start", "c")] >= max(t[("end", "a")], t[("end", "b")])


def test_events_are_emitted_in_order_from_the_main_thread():
    events = []
    agent = Agent(ScriptedProvider([calls(call("slow_read", id="1", name="a", seconds=0.2),
                                          call("slow_read", id="2", name="b", seconds=0.01)), final("ok")]),
                  [slow_read], "s",
                  on_event=lambda k, d: events.append((k, d.id if k == "tool_call" else d[0].id, threading.current_thread().name))
                  if k in ("tool_call", "tool_result") else None)
    agent.run("go")
    assert [(k, i) for k, i, _ in events] == [("tool_call", "1"), ("tool_call", "2"),
                                              ("tool_result", "1"), ("tool_result", "2")]
    assert {name for _, _, name in events} == {"MainThread"}
