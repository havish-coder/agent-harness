"""Lesson 36: how many tokens is this conversation?

The model server counts exactly, but only *after* it has read the prompt, and when a prompt is too
long some servers cut it silently and report a count that no longer describes the conversation.
(Measured on Ollama: with `num_ctx` 8192 a 9,000-word conversation was cut to 45 reported tokens
and the model had forgotten the start.) So the harness keeps its own estimate, checks it *before*
each call, and calibrates it against what the server reports when the report can be trusted.

The estimate counts characters by kind, because the tokenizer treats them differently: a letter is
about 0.2 of a token (words are long), a digit about 1.5 (digits are split one by one), punctuation
about 0.5, white space 0.2. Fitted on 55 samples of this project's own text and tool output with
qwen3's tokenizer, it was within 3% on average and within -14% / +19% in the worst cases; the
common "characters / 4" rule was 6% low on average and 63% low on digit-heavy output.
"""
import json
from dataclasses import dataclass, field

from harness.messages import Message

LETTER, DIGIT, PUNCT, SPACE = 0.2, 1.45, 0.5, 0.2      # tokens per character, by kind (fitted, see above)
MESSAGE_OVERHEAD = 4                                   # role markers and separators around each message
CALL_OVERHEAD = 8                                      # a tool call's id and wrapper, beyond its name and arguments


def estimate_tokens(text: str) -> int:
    """Tokens in `text`, estimated from the kinds of characters in it."""
    if not text:
        return 0
    letters = digits = spaces = 0
    for ch in text:
        if ch.isalpha():
            letters += 1
        elif ch.isdigit():
            digits += 1
        elif ch in " \t\r\n":
            spaces += 1
    punct = len(text) - letters - digits - spaces
    return round(letters * LETTER + digits * DIGIT + punct * PUNCT + spaces * SPACE)


def message_tokens(message: Message) -> int:
    total = MESSAGE_OVERHEAD + estimate_tokens(message.content or "")
    for call in message.tool_calls:
        total += CALL_OVERHEAD + estimate_tokens(call.name) + estimate_tokens(json.dumps(call.arguments, default=str))
    return total


def schema_tokens(schemas: list[dict]) -> int:
    return estimate_tokens(json.dumps(schemas, separators=(",", ":"))) if schemas else 0


@dataclass
class Breakdown:
    """Where the tokens of a conversation go."""
    system: int = 0
    tools: int = 0            # the tool definitions sent with every request
    user: int = 0
    assistant: int = 0
    results: dict[str, int] = field(default_factory=dict)       # tool name → tokens of its results

    @property
    def total(self) -> int:
        return self.system + self.tools + self.user + self.assistant + sum(self.results.values())


def breakdown(messages: list[Message], schemas: list[dict] | None = None) -> Breakdown:
    out = Breakdown(tools=schema_tokens(schemas or []))
    for m in messages:
        n = message_tokens(m)
        if m.role == "system":
            out.system += n
        elif m.role == "user":
            out.user += n
        elif m.role == "assistant":
            out.assistant += n
        else:
            out.results[m.tool_name or "tool"] = out.results.get(m.tool_name or "tool", 0) + n
    return out


@dataclass
class Calibrator:
    """Corrects the estimate with what the server reports, when the report is believable."""
    ratio: float = 1.0
    samples: int = 0

    def observe(self, estimated: int, reported: int) -> None:
        """`reported` is what the server said it read. A report far below the estimate means the server
        cut the prompt (it reports what was left), so it says nothing about our estimate: ignore it."""
        if estimated <= 0 or reported < 0.6 * estimated:
            return
        seen = reported / estimated
        self.ratio = min(1.6, max(0.7, seen if self.samples == 0 else 0.7 * self.ratio + 0.3 * seen))
        self.samples += 1

    def apply(self, estimated: int) -> int:
        return round(estimated * self.ratio)


@dataclass
class ContextStatus:
    estimated: int            # calibrated estimate of the next request
    raw: int                  # the estimate before calibration
    limit: int                # tokens the conversation may use: the window minus room for the reply
    window: int
    level: str                # "ok", "warn" (>= 70% of the limit), "critical" (>= 90%), "full" (over it)
    breakdown: Breakdown

    @property
    def percent(self) -> int:
        return round(100 * self.estimated / self.window) if self.window else 0


@dataclass
class ContextBudget:
    window: int
    reserve: int = 0                 # kept free for the reply
    margin: float = 1.1              # estimates can run low on some text; decisions are made on estimate * margin
    warn: float = 0.70
    critical: float = 0.90
    calibrator: Calibrator = field(default_factory=Calibrator)

    @property
    def limit(self) -> int:
        return max(1, self.window - self.reserve)

    def check(self, messages: list[Message], schemas: list[dict] | None = None) -> ContextStatus:
        parts = breakdown(messages, schemas)
        raw = parts.total
        estimated = self.calibrator.apply(raw)
        decided = estimated * self.margin
        level = ("full" if decided >= self.limit else "critical" if decided >= self.critical * self.limit
                 else "warn" if decided >= self.warn * self.limit else "ok")
        return ContextStatus(estimated, raw, self.limit, self.window, level, parts)

    def to_free(self, status: ContextStatus, share: float) -> int:
        """How many (uncalibrated) estimate tokens to remove for the decision figure to fall to `share` of the limit."""
        scale = self.calibrator.ratio * self.margin
        return max(0, round(status.raw - share * status.limit / scale))

    def observe(self, status: ContextStatus, reported_input_tokens: int) -> None:
        self.calibrator.observe(status.raw, reported_input_tokens)
