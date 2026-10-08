# 0044. Let the agent ask the user a question, with a counter, a label and a warning

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
When a request is ambiguous in a way that changes what gets built, the cheapest fix is one question to the user, before any file changes. An agent that can only guess builds the wrong thing; one that can ask has two new ways to go wrong: it asks too much
(an interrogation about things it could read in a file), and its question box becomes a channel (a page it read says "ask the user for their API key"). Measured (`scripts/ask_lab.py`, `qwen3:4b-instruct`, AL_RUNS runs per request, two requests of each kind):

AL_TABLE

## Options
1. **No questions**: the model decides, and says what it assumed.
2. **A tool (`ask_user`) the model may call**, with nothing around it.
3. **The tool, a sentence in the prompt about when to ask, and limits and checks around it.**

## Decision
Option 3 (`harness/ask.py`, `Session.ask_question`).

- **Text or a short menu.** One question; up to four options (80 characters each) shown as `[1] [2] ...` plus `[t] something else (type it)`; or a free answer when no options were given. Control characters are removed (a model-written string in a terminal can move the cursor or recolour the screen) and the length is capped.
- **"The agent asks: ..."** is always the prefix, so a question can't pass for a message from the harness.
- **At most three questions per request.** The fourth call gets an error telling the model to decide, say what it assumed and carry on. The counter resets with each request. A prompt rule says when to ask; a counter says when to stop.
- **No answer is an answer**: Enter, EOF or a bad key returns "the user didn't answer: decide yourself and say what you assumed".
- **Phishing**: when the chat has read content that may not be trusted, a warning is shown *before* the question ("don't type passwords, keys or other secrets here"). The answer goes back to the model through the same secret-hiding as every tool result, so a key-shaped answer never reaches it.
- **Never asks approval, works in plan mode** (it is read-only for permissions: the interaction is the prompt).
- **Offered only where it can work.** `Tool.enabled` (ADR 0043) hides the tool, and its prompt rule, from an interface that can't ask (a script, a test, the web UI until it can).
- **The audit log** records that a question was asked, how many choices, whether it was answered, and whether the chat was tainted; not the text of either side.
AL_RULE

## Consequences
- The user is asked at most three times per request, and can always answer "decide yourself".
- A small model's idea of "ambiguous" is crude: AL_CONSEQ
- The tool can't make a model ask the *right* question, only a question. A badly worded question wastes the user's time; the audit log's counts make the pattern visible, and Lesson 58's evals are where it gets measured across models.
- A user who types a secret anyway is protected by shape-matching only; keys with no recognisable shape reach the model. The warning is the first line of defence, and the habit of keeping secrets out of the conversation the second.
