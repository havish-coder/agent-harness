# 0036. Summarise the older conversation when clearing is not enough, and clear only what the model has used

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
[ADR 0035](0035-clear-old-tool-results-before-anything-else.md) replaced old results of re-runnable tools with notes. It finishes
tasks that act on each result as they go, and it loses data in tasks that *collect* from several results for an answer at the end,
because the only copy was the result. Something has to keep what the results said: a **summary**, written by the model, of the
older part of the conversation.

We measured several ways of using the two mechanisms on `qwen3:4b-instruct` (8,192-token window; five files of about 2,100 tokens each;
3 runs per row; `scripts/micro_lab.py`):

| Policy | **gather** (read all five, then give each file's code word) | **work** (read each, then append its code word to a file) |
|---|---|---|
| clear old results (ADR 0035) | finished 3/3, code words **3/15** | finished 3/3, **15/15** |
| summarise only | finished 3/3, **15/15**; 4 summaries a run, 28 s each | finished 3/3, **10/15**; 4.7 summaries a run, 32 s each; it read only 3.3 of the 5 files |
| clear first, then summarise (the order we shipped first) | finished 3/3, **3/15**; 0 summaries | |
| clear what was used, then summarise (a first try, with the two flaws below) | finished 3/3, **15/15**; 4 summaries a run | 3/3, **13/15**; 3.3 summaries a run, 35 s each |
| **the policy below** | finished 3/3, **15/15**; 4 summaries a run, 29 s each | finished 3/3, **15/15**; 4 clears, **0 summaries** |

The third row is the finding: with clearing first, the window never got full enough for a summary, because clearing had already thrown
away results nobody had used yet. The setting that was supposed to be a safety net (`auto_compact`) did nothing, and four of every
five code words were missing from the answers. Summarising is the safe mechanism and clearing is the cheap one; the order has to put safety first without giving up the cheap
case.

A summary is not free. On this machine each took **about 29 seconds** (it reads a shortened transcript and writes up to about 900 tokens),
against 0 for a clear and 1.6 s of cache cost.

## Options
1. **Summarise only.** Correct, and slow: every task that fills the window pays for summaries even when nothing would have been lost.
2. **Clear first, summarise if still too full** (what we had). Fast, and silently wrong for collecting tasks.
3. **Clear only results the model has used; summarise when that isn't enough; clear the rest only as a last resort.**
4. **Ask the model which results it still needs** before clearing. A model call per decision and a 4B model's judgement.

## Decision
Option 3.

- **A result is *used* when, later in the conversation, the model wrote something (a reply with text) or made a call that changes things
  (`not tool.is_read_only(args)`).** A model that only went on reading has not used what it read: the result is the only copy. (`digested_after` in
  `harness/context/micro.py`; the agent supplies the read-only test.) Work tasks (read, then act) qualify at once, collecting tasks don't.
- **The order before each model call:** (1) from 70% clear *used* results, oldest first, down to half, keeping the newest two (and the newest one
  only if the conversation doesn't fit); (2) if it still doesn't fit, summarise the older part (`harness/context/compact.py`); (3) if still `full`,
  clear unused results too, keeping the newest one; (4) otherwise stop with `context_full`.
- **Two things the lab corrected.** "The newest two" counts only results big enough to be worth a note: a one-line command result between two
  file reads used up a slot in our first version, which left the older file read protected. And the summary is triggered by `full`, not by
  `critical` (90%): in an 8K window the fixed prompt and tool definitions plus *one* file read already come to 90%, so a 90% trigger asked for
  a summary (30 seconds) after every clear, when a clear alone was enough (work task: 13 of 15 code words and 3.7 summaries a run, against 15 of 15
  with none). A summary answers "this doesn't fit", and the check runs before every call, so nothing is ever sent that doesn't.
- **What is summarised.** Everything except the system prompt and a verbatim tail: the newest 30% of the budget, extended to always include the last
  exchange (the newest call and its results), cut only between messages. The summariser sees the older part in a shortened form (each result cut
  to 400, then 200, then 80 characters; then oldest messages dropped) so the request fits, with no tools, in three headings: Request, Done, Open.
- **The rebuilt conversation:** system prompt, one user message with the summary, the user's **current request word for word** (a summary can
  drop a requirement), and a one-line "carry on and cover the whole request" note, then the kept messages.
- **A summary of untrusted reading is untrusted.** When the permissions say this chat has read content nobody vouches for and fencing is on, the summary
  is wrapped in `<untrusted source="summary of earlier steps">`, closing tags inside it defused like any fenced text. Otherwise compaction would turn a web
  page's words into text that looks like the harness's own ([ADR 0028](0028-fence-and-taint-untrusted-content.md)).
- **Failure changes nothing.** A model error or an empty summary leaves the conversation as it was and is reported; **three failures in a row stop the
  automatic attempts** (a manual `/compact` still tries). The summary call counts as a model call for costs and limits.
- **Nothing is lost for the user.** The replaced messages are kept in `agent.archive`; `/export` writes them, and leaves the summary text out.
- Setting `auto_compact` (default on) and `/compact [what to keep in mind]`.

## Consequences
- Collecting tasks now finish correctly in a window too small to hold their results, at about half a minute per summary on a 4B local model.
  Cloud models and larger GPUs are faster; the user can turn the automatic summary off, and `clear` still handles work tasks without any model call.
- A summary is only as good as the summariser and the shortened text it sees. A fact deeper than 400 characters into a result, and not mentioned by the
  model itself, can be lost; the lab put the code word on line one, which is a favourable case. A later lesson's memory and journal are for what must survive.
- The next request after a summary is read from scratch by the server (the start of the conversation changed), like any compaction.
- A model that never writes anything between tool calls and never changes anything (a long read-only investigation) is summarised, not cleared; that is the
  intended cost.
