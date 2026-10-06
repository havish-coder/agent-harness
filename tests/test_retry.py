"""Lesson 19: retries, backoff, budgets, streams and fallback, without ever really sleeping."""
import random

import pytest

from harness.agent import Agent
from harness.messages import Message
from harness.providers.base import ProviderError, TextDelta
from harness.providers.fake import ScriptedProvider, text
from harness.providers.retry import RetryingProvider


class Flaky:
    """Fails with the given errors, then answers."""
    model = "flaky"

    def __init__(self, *errors, answer="ok"):
        self.errors, self.answer, self.calls = list(errors), answer, 0

    def chat(self, messages, tools):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return text(self.answer)


class FlakyStream(Flaky):
    def __init__(self, *errors, fail_after_text=False):
        super().__init__(*errors)
        self.fail_after_text = fail_after_text

    def stream(self, messages, tools):
        self.calls += 1
        if self.errors and not self.fail_after_text:
            raise self.errors.pop(0)
        yield TextDelta("Hel")
        if self.errors:
            raise self.errors.pop(0)
        yield TextDelta("lo")
        yield text("Hello")


def server_error(retry_after=None):
    return ProviderError("HTTP 500: CUDA error", status=500, retryable=True, retry_after=retry_after)


def wrap(inner, **kw):
    sleeps, notices = [], []
    provider = RetryingProvider(inner, sleep=sleeps.append, on_retry=notices.append, rng=random.Random(0), **kw)
    return provider, sleeps, notices


def test_retries_then_succeeds_with_growing_delays():
    inner = Flaky(server_error(), server_error(), server_error())
    provider, sleeps, notices = wrap(inner)
    assert provider.chat([Message.user("hi")], []).message.content == "ok"
    assert inner.calls == 4 and len(sleeps) == 3
    for delay, base in zip(sleeps, [0.5, 1.0, 2.0], strict=True):
        assert 0.75 * base <= delay <= 1.25 * base           # exponential, with ±25% jitter
    assert [n.attempt for n in notices] == [1, 2, 3]
    assert provider.model == "flaky"


def test_permanent_errors_are_not_retried():
    inner = Flaky(ProviderError("HTTP 401: bad key", status=401, retryable=False))
    provider, sleeps, _ = wrap(inner)
    with pytest.raises(ProviderError, match="bad key"):
        provider.chat([], [])
    assert inner.calls == 1 and sleeps == []


def test_gives_up_after_max_retries():
    inner = Flaky(*[server_error() for _ in range(10)])
    provider, sleeps, _ = wrap(inner, max_retries=2)
    with pytest.raises(ProviderError, match="CUDA"):
        provider.chat([], [])
    assert inner.calls == 3 and len(sleeps) == 2


def test_retry_after_is_respected_and_budget_is_enforced():
    provider, sleeps, _ = wrap(Flaky(server_error(retry_after=7)))
    provider.chat([], [])
    assert sleeps == [7]
    inner = Flaky(server_error(retry_after=30), server_error(retry_after=30))
    provider, sleeps, _ = wrap(inner, budget=40)
    with pytest.raises(ProviderError):
        provider.chat([], [])
    assert sleeps == [30]                                    # a second 30 s wait would exceed the budget


def test_delays_are_capped():
    provider, _, _ = wrap(Flaky(), max_delay=5)
    assert all(provider.delay(attempt, server_error()) <= 5 * 1.25 for attempt in range(1, 20))


def test_fallback_after_retries_are_used_up():
    backup = ScriptedProvider([text("from the backup model")], model="backup")
    provider, _, notices = wrap(Flaky(*[server_error() for _ in range(5)]), max_retries=1, fallback=backup)
    assert provider.chat([], []).message.content == "from the backup model"
    assert notices[-1].fallback


def test_stream_retries_only_before_the_first_text():
    inner = FlakyStream(server_error())
    provider, sleeps, _ = wrap(inner)
    items = list(provider.stream([], []))
    assert items[:2] == [TextDelta("Hel"), TextDelta("lo")] and items[-1].message.content == "Hello"
    assert len(sleeps) == 1

    inner = FlakyStream(server_error(), fail_after_text=True)
    provider, sleeps, _ = wrap(inner)
    stream = provider.stream([], [])
    assert next(stream) == TextDelta("Hel")
    with pytest.raises(ProviderError):                        # text was already shown: no silent restart
        list(stream)
    assert sleeps == []


def test_agent_with_a_retrying_provider():
    provider, _, notices = wrap(Flaky(server_error(), answer="done"))
    agent = Agent(provider, [], "s")
    assert agent.run("go") == "done" and len(notices) == 1
