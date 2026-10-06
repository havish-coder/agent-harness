# Testing

Agent behaviour depends on a model that is slow, needs a GPU and never answers the same way
twice. The test suite therefore has three layers, and only the last one talks to a model.

| Layer | What it checks | Model | Runs |
|---|---|---|---|
| **Unit tests** | tools, validation, the loop's rules | none, or `ScriptedProvider` | always (`pytest`) |
| **Replay tests** | a real recorded run still behaves the same | `ReplayProvider` (a cassette) | always (`pytest`) |
| **Live tests** | the real model can still do basic tasks | Ollama | on demand (`pytest -m live`) |

```bash
pytest                     # unit + replay tests, about 20 seconds, no model needed
pytest -m live             # live tests (Ollama with qwen3:4b-instruct must be running)
pytest --cov=harness       # with a coverage report
```

## Scripted replies
`harness.providers.fake.ScriptedProvider` returns replies you write, in order, and records the
requests it received:

```python
from harness.agent import Agent
from harness.messages import ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls

provider = ScriptedProvider([tool_calls(ToolCall("1", "read_file", {"path": "notes.txt"})),
                             text("There are 3 TODOs.")])
agent = Agent(provider, tools, "system prompt", approve=lambda call, tool: True)
assert agent.run("How many TODOs?") == "There are 3 TODOs."
assert provider.requests[1][0][-1].role == "tool"     # the second request carried the result
```

## Cassettes: record once, replay forever
A **cassette** (`tests/cassettes/*.jsonl`) is a recording of a real run: for every model call,
the messages the agent sent, the tool names, and the model's reply.

- `RecordingProvider(real_provider, path, root=workspace)` writes one.
- `ReplayProvider(path, root=workspace)` plays it back. In **strict** mode (the default) every
  request must match the recording exactly; any difference raises `ReplayMismatch` with a diff
  of the first message that changed.

Replaying runs the **real tools** on a fresh copy of the workspace. So a replay test fails when
a tool's output changes, the system prompt changes, or the loop sends something different, all
without a model.

Text that differs between machines and runs is normalized before comparing: the workspace
path becomes `[WS]`, the home folder `[HOME]`, the Python installation `[PYTHON]`, timings
`[T]s`, and Windows backslashes in those paths become `/`. A test checks that no cassette
contains your home folder path.

### Re-recording
When a change is intended (you improved a tool's output), the replay test fails. Re-record:

```bash
python scripts/record_cassette.py fix_subtotal "The cart subtotal in project/shop/cart.py ignores the quantity. Fix it. Then run the project's tests with run_shell to check."
```

The script copies `workspace/` to a temporary folder, runs the task with temperature 0 and every
call approved, saves the cassette and prints whether the project's tests pass. Review the new
cassette's `git diff` like code: it shows exactly how the agent's behaviour changed.

## Live tests
Mark them with `@pytest.mark.live`. They are deselected by default (`addopts` in
`pyproject.toml`). Assert on behaviour (a tool was used, the answer contains a fact), never on
exact wording.

## Security tests: the attack lab
`tests/security/` holds one test per attack from the [threat model](../security.md). Each test
is written as the **safe outcome** ("the secret is not in anything the model saw", "no file was
planted outside the workspace"), using the `lab` fixture: a temporary workspace with a secret
file next to it, a link pointing out of it, a `.git/hooks/` folder, a `.env` file and a fake API
key in the environment. `lab.attack(call(...), ...)` plays a hostile model: the calls go through
the real agent loop, tools and approval path, and it returns the tool results the model saw.

```python
def test_t1_read_outside_with_dotdot(lab):
    assert SECRET not in lab.attack(call("read_file", path="../outside/secret.txt"))
```

`python scripts/attack_report.py` runs the lab and prints, per threat, how many attacks are stopped and which are
known to get through. Tests that need an OS sandbox use it automatically when the machine has one.

An attack the harness can't stop yet is marked `@fixed_in("28 (path jail)")`, an
`xfail(strict=True)`: the suite stays green, and the moment the defense works the test
"unexpectedly passes", which strict mode reports as a failure until you remove the marker.
Check that every expected failure fails **for the right reason** (the attack really worked, not a
setup error) with:

```bash
pytest tests/security --runxfail
```

When you add a defense, add the attack it stops first, watch it fail, then make it pass.

### Prompt-injection lab
`scripts/injection_lab.py` measures how often the real model follows instructions planted in
content (a code comment, a README, a data file posing as a user message). Read-only tools run;
every other call is recorded and denied, so nothing actually happens. It needs Ollama:

```bash
python scripts/injection_lab.py 3
```
