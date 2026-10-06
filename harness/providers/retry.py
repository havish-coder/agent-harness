"""Lesson 19: retries with exponential backoff, and a fallback model.

Model servers fail in temporary ways: a GPU runner crashes (Ollama returned HTTP 500 during
this project), a cloud API is overloaded (529) or rate-limits us (429), a connection drops.
`RetryingProvider` wraps any provider and tries again when an error says it's worth it
(`ProviderError.retryable`), waiting longer each time.

Rules:
- Only retryable errors are retried. A bad key or an unknown model fails at once.
- Waits grow exponentially with random jitter, and are capped; a server's Retry-After wins.
- A total time budget stops endless waiting.
- A stream is only retried if it failed before producing any text: once words are on the
  screen, silently starting over would show the user two different answers.
- After the retries are used up, an optional fallback provider gets one chance.
"""
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from harness.messages import Message, Reply
from harness.providers.base import Provider, ProviderError, StreamingProvider, StreamItem


@dataclass
class RetryNotice:
    """Passed to on_retry so an interface can say what's happening."""
    attempt: int          # 1 = the first retry
    delay: float          # seconds until the next attempt
    error: ProviderError
    fallback: bool = False  # True when switching to the fallback provider instead of waiting


class RetryingProvider:
    def __init__(self, inner: Provider, max_retries: int = 4, base_delay: float = 0.5, max_delay: float = 20.0,
                 budget: float = 90.0, fallback: Provider | None = None,
                 on_retry: Callable[[RetryNotice], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None):
        self.inner = inner
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.budget = budget              # total seconds we may spend waiting, per call
        self.fallback = fallback
        self.on_retry = on_retry or (lambda notice: None)
        self.sleep = sleep                # injectable, so tests don't actually wait
        self.rng = rng or random.Random()

    @property
    def model(self) -> str:
        return self.inner.model

    def __repr__(self):
        return f"RetryingProvider({self.inner!r})"

    def delay(self, attempt: int, error: ProviderError) -> float:
        """Exponential backoff with jitter: about 0.5, 1, 2, 4... seconds, capped."""
        if error.retry_after is not None:
            return min(error.retry_after, self.budget)     # the server knows best
        base = min(self.max_delay, self.base_delay * 2 ** (attempt - 1))
        return base * (0.75 + 0.5 * self.rng.random())     # ±25%, so clients don't retry in lockstep

    def _attempts(self, call: Callable[[Provider], object]):
        """Run `call(provider)` with retries; the shared logic of chat() and stream()."""
        waited = 0.0
        last: ProviderError | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                return call(self.inner)
            except ProviderError as e:
                if not e.retryable:
                    raise
                last = e
                if attempt > self.max_retries:
                    break
                wait = self.delay(attempt, e)
                if waited + wait > self.budget:
                    break
                self.on_retry(RetryNotice(attempt, wait, e))
                self.sleep(wait)
                waited += wait
        if self.fallback is not None:
            self.on_retry(RetryNotice(self.max_retries + 1, 0.0, last, fallback=True))
            return call(self.fallback)
        raise last

    def chat(self, messages: list[Message], tools: list[dict]) -> Reply:
        return self._attempts(lambda p: p.chat(messages, tools))

    def stream(self, messages: list[Message], tools: list[dict]) -> Iterator[StreamItem]:
        def start(provider: Provider):
            """Open the stream and pull its first item, so early failures can be retried."""
            if not isinstance(provider, StreamingProvider):
                return iter([provider.chat(messages, tools)]), None
            items = provider.stream(messages, tools)
            return items, next(items, None)    # raises here if the request itself fails

        items, first = self._attempts(start)
        if first is not None:
            yield first
        yield from items                       # failures after this point are not retried
