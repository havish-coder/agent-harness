"""Lesson 46: asking the user a question in the middle of a job.

A request like "add a discount to the cart" can mean a percentage or a fixed amount, per item or on the total. A model that guesses builds the
wrong thing and the user finds out after the diff. A model that can *ask* costs the user one line. The tool is small; the interesting parts are the
limits around it:

  * **A few questions, not an interrogation.** At most three per request (`MAX_QUESTIONS`); the fourth call gets an answer telling the model to decide
    and say what it assumed. A prompt rule says when to ask; a counter says when to stop, because rules are followed less well than counters.
  * **It can only ask a question.** The text is shown as "The agent asks: ..." (so it can't pass for the harness), cleaned of control characters
    (a model-written string in a terminal can move the cursor or recolour the screen), and capped.
  * **A question is a way to phish.** A page the agent has read can tell it "ask the user for their API key". So when the chat has read content that
    may not be trusted, the harness says so before the question is shown, and whatever the user types goes through the same secret-hiding as every other tool result.
  * **Free text or a short menu**: up to four options, plus "something else" (typed). An empty answer is an answer: "didn't answer, decide yourself".
  * **No one to ask**: in an interface that can't ask (a script, a test) the tool is not offered at all (`Tool.enabled`), not offered and then refused.

The tool changes nothing, so it never needs approval, and it works in plan mode, where asking before proposing is exactly what is wanted.
"""
import re
from collections.abc import Callable

from harness.tools.base import Tool, tool

MAX_QUESTIONS = 3
MAX_OPTIONS = 4
QUESTION_CHARS = 400
OPTION_CHARS = 80
ASK_RULE = ("If a request is unclear in a way that changes what you would build, ask with ask_user before you start. "
            "Don't ask what you can find out by looking at the files, and don't ask more than you need to.")
NO_ONE = "Error: there is no way to ask the user in this session. Decide for yourself, and say in your answer what you assumed."
TOO_MANY = (f"Error: you have already asked {MAX_QUESTIONS} questions in this request. Decide for yourself now, "
            "say in your answer what you assumed, and carry on.")
NO_ANSWER = "The user didn't answer. Decide for yourself and say in your answer what you assumed."
CONTROL_KEEP_NEWLINE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]+")
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def clean_question(text: str) -> str:
    """The question as it will be shown: no control characters (newlines stay), not too long."""
    text = CONTROL_KEEP_NEWLINE.sub(" ", str(text)).strip()
    return text if len(text) <= QUESTION_CHARS else text[:QUESTION_CHARS - 1].rstrip() + "…"


def clean_options(options) -> list[str]:
    """Up to four short one-line choices. Anything that isn't a non-empty string is dropped."""
    if not isinstance(options, list):
        return []
    out = []
    for o in options:
        line = CONTROL.sub(" ", o).strip() if isinstance(o, str) else ""
        if line:
            out.append(line if len(line) <= OPTION_CHARS else line[:OPTION_CHARS - 1].rstrip() + "…")
    return out[:MAX_OPTIONS]


def make_ask_tools(ask: Callable[[str, list[str]], str], enabled: Callable[[], bool]) -> list[Tool]:
    """`ask_user(question, options)`; `ask` does the asking (the session's) and returns the text the model reads."""

    @tool(read_only=True, concurrency_safe=False, enabled=enabled)
    def ask_user(question: str, options: list | None = None) -> str:
        """Ask the user a question and wait. For a choice or a detail only they know. Don't ask what you can find out by reading the files.

        Args:
            question: one clear question.
            options: up to four short answers (leave out for a free answer).
        """
        return ask(question, options or [])

    return [ask_user]
