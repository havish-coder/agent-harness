"""Lesson 21: token accounting and cost, including prompt-cache reads and writes."""
import pytest

from harness.config import ConfigError, load_settings
from harness.messages import Message, Reply, Usage
from harness.usage import FREE, CostTracker, Price, format_cost, price_for


def reply(model, **usage):
    return Reply(Message("assistant", "x"), "end", Usage(**usage), model=model)


def test_cost_counts_cache_reads_and_writes_at_their_own_price():
    sonnet = price_for("anthropic", "claude-sonnet-5-5")
    assert sonnet == Price(2, 10, cache_write=2.5, cache_read=0.20)
    u = Usage(input_tokens=100_000, output_tokens=1_000, cache_read_tokens=90_000, cache_write_tokens=5_000)
    # 5,000 uncached × $2 + 5,000 written × $2.50 + 90,000 read × $0.20 + 1,000 out × $10, per million
    assert sonnet.cost(u) == pytest.approx((5_000 * 2 + 5_000 * 2.5 + 90_000 * 0.2 + 1_000 * 10) / 1e6)
    assert Price(1, 2).cost(Usage(1_000_000, 1_000_000, cache_read_tokens=500_000)) == pytest.approx(3.0)


def test_price_lookup():
    assert price_for("anthropic", "claude-haiku-4-5-20251001").input == 1        # dated model names
    assert price_for("anthropic", "claude-opus-5-5").input == 4                   # longest prefix wins
    assert price_for("anthropic", "claude-opus-5").input == 5
    assert price_for("ollama", "qwen3:4b-instruct") is FREE                       # your own machine
    assert price_for("groq", "llama-3.3-70b-versatile") is None                   # unknown: never "free"
    custom = {"llama-3.3": {"input": 0.59, "output": 0.79}}
    assert price_for("groq", "llama-3.3-70b-versatile", custom) == Price(0.59, 0.79)


def test_tracker_by_model_and_unknown_prices():
    tracker = CostTracker("anthropic", "claude-sonnet-5-5")
    tracker.add(reply("claude-sonnet-5-5", input_tokens=10_000, output_tokens=500, cache_read_tokens=8_000))
    tracker.add(reply(None, input_tokens=12_000, output_tokens=300, cache_read_tokens=10_000))   # default model
    tracker.add(reply("claude-haiku-4-5-20251001", input_tokens=1_000, output_tokens=100))       # a fallback
    assert tracker.models["claude-sonnet-5-5"].calls == 2
    assert tracker.total_usage().input_tokens == 23_000
    assert tracker.cost() == pytest.approx((4_000 * 2 + 18_000 * 0.2 + 800 * 10 + 1_000 * 1 + 100 * 5) / 1e6)
    assert "18,000 read from cache" in tracker.summary()
    tracker.add(reply("mystery-model", input_tokens=1, output_tokens=1))
    assert tracker.cost() is None and "price unknown" in tracker.summary()


def test_format_cost():
    assert (format_cost(0), format_cost(0.0012), format_cost(1.234)) == ("free", "$0.0012", "$1.23")


def test_prices_setting_merges_and_is_validated(tmp_path, monkeypatch):
    from harness import config
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "settings.json").write_text('{"prices": {"a": {"input": 1, "output": 2}}}', encoding="utf-8")
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "settings.json").write_text('{"prices": {"b": {"input": 3, "output": 4}}}', encoding="utf-8")
    settings, _ = load_settings(tmp_path, environ={})
    assert set(settings.prices) == {"a", "b"}
    (tmp_path / ".harness" / "settings.json").write_text('{"prices": {"b": {"input": "3"}}}', encoding="utf-8")
    with pytest.raises(ConfigError, match="dollars per million tokens"):
        load_settings(tmp_path, environ={})


def test_adapters_report_cached_tokens():
    from harness.providers.anthropic import from_anthropic
    from harness.providers.ollama import from_ollama
    from harness.providers.openai_compat import from_openai
    o = from_ollama({"message": {"content": "x"}, "prompt_eval_count": 148, "prompt_eval_cached_count": 138,
                     "eval_count": 5, "model": "qwen3:4b-instruct"})
    assert (o.usage.input_tokens, o.usage.cache_read_tokens, o.model) == (148, 138, "qwen3:4b-instruct")
    oa = from_openai({"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}], "model": "m",
                      "usage": {"prompt_tokens": 146, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 145}}})
    assert oa.usage.cache_read_tokens == 145
    a = from_anthropic({"content": [], "stop_reason": "end_turn", "usage": {
        "input_tokens": 30, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 70, "output_tokens": 4}})
    assert (a.usage.input_tokens, a.usage.cache_read_tokens, a.usage.cache_write_tokens) == (1000, 900, 70)
