"""Lesson 59: sizing the context window from the GPU's memory and the model's shape. No GPU or Ollama needed: their answers are faked."""
from harness.context import hardware
from harness.context.hardware import (
    CEILING,
    FLOOR,
    ModelFacts,
    auto_window,
    gpu_memory,
    model_facts,
    usable_memory,
)

GIB = 2**30
QWEN = ModelFacts("qwen3:4b-instruct", 262_144, 36, 8, 128, 2_500_000_000)      # what Ollama reports for it


def test_the_cache_per_token_matches_what_ollama_reported():
    assert QWEN.per_token() == 147_456 and QWEN.per_token("q8_0") == 73_728
    at_8k = QWEN.weights + 8_192 * QWEN.per_token() + hardware.BUFFERS
    assert abs(at_8k - 4_130_487_663) / 4_130_487_663 < 0.01          # `ollama ps` said 4,130,487,663 bytes at 8K


def test_the_gpu_is_read_from_nvidia_smi(monkeypatch):
    monkeypatch.setattr(hardware, "run", lambda *c: "3765, 4094\n" if c[0] == "nvidia-smi" else "")
    assert gpu_memory() == (3765 * 2**20, 4094 * 2**20)
    monkeypatch.setattr(hardware, "run", lambda *c: "")
    monkeypatch.setattr(hardware.platform, "system", lambda: "Windows")
    assert gpu_memory() is None
    monkeypatch.setattr(hardware.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(hardware.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(hardware, "run", lambda *c: "34359738368\n" if c[0] == "sysctl" else "")
    assert gpu_memory() == (32 * GIB * 2 // 3, 32 * GIB)               # Apple silicon: shared memory, two thirds usable


def fake_ollama(info, tags, ps=None):
    return lambda base, path, body=None: {"/api/show": {"model_info": info}, "/api/tags": {"models": tags}, "/api/ps": {"models": ps or []}}[path]


def test_the_models_shape_comes_from_ollama(monkeypatch):
    info = {"qwen3.block_count": 36, "qwen3.attention.head_count_kv": 8, "qwen3.attention.key_length": 128, "qwen3.context_length": 262_144,
            "qwen3.embedding_length": 2560, "qwen3.attention.head_count": 32}
    monkeypatch.setattr(hardware, "ollama", fake_ollama(info, [{"name": "qwen3:4b-instruct", "size": 2_500_000_000}]))
    assert model_facts("qwen3:4b-instruct") == QWEN
    no_key_length = {k: v for k, v in info.items() if "key_length" not in k}
    monkeypatch.setattr(hardware, "ollama", fake_ollama(no_key_length, [{"name": "qwen3:4b-instruct", "size": 2_500_000_000}]))
    assert model_facts("qwen3:4b-instruct").head_size == 80                # 2560 / 32
    monkeypatch.setattr(hardware, "ollama", fake_ollama({}, []))
    assert model_facts("qwen3:4b-instruct") is None                         # a server that says nothing: unknown


def test_memory_ollama_already_holds_counts_as_usable(monkeypatch):
    monkeypatch.setattr(hardware, "gpu_memory", lambda: (1 * GIB, 4 * GIB))
    monkeypatch.setattr(hardware, "ollama", fake_ollama({}, [], [{"size_vram": 2 * GIB}]))
    assert usable_memory() == (3 * GIB, 4 * GIB)
    monkeypatch.setattr(hardware, "ollama", fake_ollama({}, [], [{"size_vram": 9 * GIB}]))
    assert usable_memory() == (4 * GIB, 4 * GIB)                            # never more than the GPU has


def test_a_small_gpu_keeps_8k_and_says_why():
    window, why = auto_window(QWEN, (int(3.7 * GIB), 4 * GIB))
    assert window == FLOOR and "wouldn't fit" in why and "4.0 GB GPU" in why


def test_a_bigger_gpu_gets_a_bigger_window_in_steps_of_8k():
    window, why = auto_window(QWEN, (12 * GIB, 12 * GIB))
    room = 12 * GIB - QWEN.weights - hardware.BUFFERS
    assert window == int(room // QWEN.per_token()) // 8192 * 8192 == 65_536 and "fits beside qwen3:4b-instruct" in why
    assert auto_window(QWEN, (8 * GIB, 8 * GIB))[0] == 32_768 and auto_window(QWEN, (8 * GIB, 8 * GIB), "q8_0")[0] == 73_728   # 8-bit: twice the tokens
    assert auto_window(QWEN, (12 * GIB, 12 * GIB), "q8_0")[0] == CEILING


def test_the_window_stops_at_the_models_limit_or_the_ceiling():
    small_limit = ModelFacts("tiny", 32_768, 24, 2, 64, 400_000_000)
    assert auto_window(small_limit, (24 * GIB, 24 * GIB)) == (32_768, auto_window(small_limit, (24 * GIB, 24 * GIB))[1])
    assert "the model's limit" in auto_window(small_limit, (24 * GIB, 24 * GIB))[1]
    big, why = auto_window(QWEN, (48 * GIB, 48 * GIB))
    assert big == CEILING and "ceiling" in why
    assert auto_window(ModelFacts("old", 4_096, 24, 8, 64, 400_000_000), (24 * GIB, 24 * GIB))[0] == 4_096


def test_what_cant_be_found_out_gives_8k():
    assert auto_window(None, (24 * GIB, 24 * GIB))[0] == FLOOR
    window, why = auto_window(QWEN, None)
    assert window == FLOOR and "no GPU memory found" in why


# --- the window in a session (Lesson 59) -------------------------------------------------------------------------------

def test_resolve_window_by_provider(monkeypatch):
    from harness.context import windows
    assert windows.resolve_window("ollama", "m", 20_000) == (20_000, "set to 20,000")                     # a number always wins
    assert windows.resolve_window("ollama", "m", "auto", "http://gpu-box.lan:11434")[0] == FLOOR          # another computer: not measured
    assert windows.resolve_window("anthropic", "claude-sonnet-5-5", "auto") == (200_000, "auto: 200,000 (the model's window)")
    assert "unknown cloud model" in windows.resolve_window("openai", "mystery-1", "auto")[1]
    seen = []
    monkeypatch.setattr(windows, "model_facts", lambda model, base: QWEN)
    monkeypatch.setattr(windows, "usable_memory", lambda base: (12 * GIB, 12 * GIB))
    monkeypatch.setattr(windows, "auto_window", lambda f, m, cache: seen.append(cache) or (65_536, "x"))
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q8_0")
    monkeypatch.delenv("OLLAMA_FLASH_ATTENTION", raising=False)
    windows.resolve_window("ollama", "qwen3:4b-instruct", "auto")
    monkeypatch.setenv("OLLAMA_FLASH_ATTENTION", "1")
    windows.resolve_window("ollama", "qwen3:4b-instruct", "auto")
    assert seen == ["f16", "q8_0"]                     # Ollama uses a quantized cache only with flash attention on


def test_the_window_changes_while_the_chat_goes_on(tmp_path, monkeypatch):
    from harness import config
    from harness.commands import load_commands
    from harness.config import Settings
    from harness.context.prompt import PROMPT_SHARE
    from harness.session import Session
    from harness.tui.plain import PlainUI
    from harness.workspace import Workspace
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    s = Session(Settings(save_chats=False, auto_memory="off", journal="off"), Workspace(tmp_path), PlainUI(), None)
    assert s.window == 8192 and s.provider.inner.options["num_ctx"] == 8192 and "auto" in s.window_reason
    commands = load_commands(tmp_path)

    def run(line):
        command, args = commands.parse(line)
        return command.run(s, args)
    said = run("/window 16k")
    assert s.window == s.context.window == s.agent.context.window == 16_384 and s.provider.inner.options["num_ctx"] == 16_384
    assert "16,384 tokens (set to 16,384)" in said and s.settings.context_window == 16_384 and s.settings.sources["context_window"] == "command"
    assert s.status()["context_window"] == 16_384 and s.prompt.budget == int(16_384 * PROMPT_SHARE)    # the prompt's share grew too
    assert "usage" in run("/window 100") and "usage" in run("/window lots") and s.window == 16_384
    assert "8,192 tokens" in run("/window auto") and s.window == 8192
    assert "context window: 8,192 tokens" in run("/window") and "window: auto" in run("/context")



def test_a_smaller_window_mid_chat_clears_old_results_instead_of_stopping(tmp_path, monkeypatch):
    """/window 8192 under a conversation that has outgrown it: the next request makes room and goes on (the context guide says so)."""
    from harness import config
    from harness.config import Settings
    from harness.messages import ToolCall
    from harness.providers.fake import ScriptedProvider, text, tool_calls
    from harness.session import Session
    from harness.tui.plain import PlainUI
    from harness.workspace import Workspace
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    for n in range(6):
        (tmp_path / f"part{n}.txt").write_text("".join(f"row {i:03}: value {(i * 7919 + n) % 99991:05} ok\n" for i in range(75)), encoding="utf-8")
    s = Session(Settings(save_chats=False, auto_memory="off", journal="off", todo=False, subagents=False, background_tasks=False,
                         context_window=24_576), Workspace(tmp_path), PlainUI(), None)
    s.agent.stream = False
    reads = [tool_calls(ToolCall(f"r{n}", "read_file", {"path": f"part{n}.txt"})) for n in range(6)]
    s.agent.provider = ScriptedProvider([*reads, text("read them"), text("still here")])
    s.agent.run("read every part")
    schemas = s.agent.tools.schemas()
    before = s.context.check(s.agent.messages, schemas)
    s.set_window(8_192)
    after = s.context.check(s.agent.messages, schemas)
    assert before.level == "ok" and after.level == "full" and after.limit == 8_192 - 2_048
    assert s.agent.run("what was in part0?") == "still here"
    assert s.agent.cleared_results > 0 and s.context.check(s.agent.messages, schemas).level != "full"
