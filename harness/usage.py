"""Lesson 21: what a session costs, in tokens and in money.

Cost = uncached input × input price + cache writes × write price + cache reads × read price
       + output × output price      (prices in US dollars per million tokens)

Prices change, and differ per vendor and plan, so the built-in table is small and dated: models
on your own machine cost nothing, and Anthropic's published prices (fetched on 2026-10-06 from
https://platform.claude.com/docs/en/about-claude/pricing). Anything else can be added with the
`prices` setting. A model without a known price is reported as "price unknown", never as free.
"""
from dataclasses import dataclass, field

from harness.messages import Reply, Usage


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""
    input: float
    output: float
    cache_write: float | None = None   # default: same as input
    cache_read: float | None = None    # default: same as input

    def cost(self, u: Usage) -> float:
        uncached = max(0, u.input_tokens - u.cache_read_tokens - u.cache_write_tokens)
        write = self.input if self.cache_write is None else self.cache_write
        read = self.input if self.cache_read is None else self.cache_read
        return (uncached * self.input + u.cache_write_tokens * write + u.cache_read_tokens * read
                + u.output_tokens * self.output) / 1_000_000


FREE = Price(0, 0, 0, 0)
PRICES_AS_OF = "2026-10-06"
# Model-name prefix → price. Anthropic: standard API pricing, 5-minute cache writes.
PRICES: dict[str, Price] = {
    "claude-fable-5-1": Price(10, 50, cache_write=12.5, cache_read=0.25),
    "claude-opus-5-5": Price(4, 20, cache_write=5, cache_read=0.20),
    "claude-opus-5": Price(5, 25, cache_write=6.25, cache_read=0.50),
    "claude-sonnet-5-5": Price(2, 10, cache_write=2.5, cache_read=0.20),
    "claude-sonnet-5": Price(2, 10, cache_write=2.5, cache_read=0.20),
    "claude-sonnet-4-6": Price(3, 15, cache_write=3.75, cache_read=0.30),
    "claude-sonnet-4-5": Price(3, 15, cache_write=3.75, cache_read=0.30),
    "claude-haiku-4-5": Price(1, 5, cache_write=1.25, cache_read=0.10),
}
LOCAL_PROVIDERS = {"ollama", "ollama-openai", "lmstudio"}


def price_for(provider: str, model: str | None, overrides: dict | None = None) -> Price | None:
    """Look a model up: user overrides first, then the built-in table (longest matching prefix)."""
    model = model or ""
    for table in (_parse(overrides or {}), PRICES):
        matches = [name for name in table if model.startswith(name)]   # "claude-haiku-4-5-20251001" too
        if matches:
            return table[max(matches, key=len)]
    if provider in LOCAL_PROVIDERS:
        return FREE
    return None


def _parse(raw: dict) -> dict[str, Price]:
    return {name: Price(**p) if isinstance(p, dict) else p for name, p in raw.items()}


@dataclass
class ModelTotals:
    calls: int = 0
    usage: Usage = field(default_factory=Usage)


class CostTracker:
    """Adds up usage per model over a session. Feed it every Reply (the model_reply event)."""

    def __init__(self, provider: str, default_model: str, overrides: dict | None = None):
        self.provider, self.default_model, self.overrides = provider, default_model, overrides or {}
        self.models: dict[str, ModelTotals] = {}

    def add(self, reply: Reply) -> None:
        totals = self.models.setdefault(reply.model or self.default_model, ModelTotals())
        totals.calls += 1
        totals.usage += reply.usage

    def total_usage(self) -> Usage:
        total = Usage()
        for t in self.models.values():
            total += t.usage
        return total

    def cost(self) -> float | None:
        """Total dollars, or None if any model's price is unknown."""
        total = 0.0
        for model, t in self.models.items():
            price = price_for(self.provider, model, self.overrides)
            if price is None:
                return None
            total += price.cost(t.usage)
        return total

    def summary(self) -> str:
        lines = []
        for model, t in self.models.items():
            u = t.usage
            price = price_for(self.provider, model, self.overrides)
            money = "price unknown" if price is None else format_cost(price.cost(u))
            cached = f", {u.cache_read_tokens:,} read from cache" if u.cache_read_tokens else ""
            written = f", {u.cache_write_tokens:,} written to cache" if u.cache_write_tokens else ""
            lines.append(f"{model}: {t.calls} call{'s' if t.calls != 1 else ''}, {u.input_tokens:,} input{cached}{written}, "
                         f"{u.output_tokens:,} output tokens · {money}")
        return "\n".join(lines) or "no model calls yet"


def format_cost(dollars: float) -> str:
    if dollars == 0:
        return "free"
    if dollars < 0.01:
        return f"${dollars:.4f}"
    return f"${dollars:.2f}"
