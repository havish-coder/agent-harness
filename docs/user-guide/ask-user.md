# Questions from the agent

A request like *"add a coupon feature"* can mean a percentage or a fixed amount, one use or many. A model that guesses builds the wrong thing and you find out in the diff. So the agent has a tool, **`ask_user`**, to ask you
instead: one clear question, and up to four short answers to choose from.

```text
> Add a coupon feature to the cart

The agent asks: Should a coupon take off a percentage or a fixed amount?
  [1] a percentage / [2] a fixed amount / [t] something else (type it): 2
● edit_file(path='project/shop/cart.py', ...)
```

- The question is always shown as **"The agent asks: ..."**, so it can't pass for a message from the harness.
- Pick a number, or `t` and type your own answer. Enter, or no answer, tells the agent you didn't answer: it decides for itself and says what it assumed.
- **At most three questions per request.** The fourth gets "decide for yourself and say what you assumed". A rule in the prompt says when to ask; a counter makes sure it stops.
- It **never asks for approval** (it changes nothing), and it works in [plan mode](plan-mode.md), where asking before proposing is what you want.
- In an interface that can't ask (a script, an automated run) the tool is **not offered at all**.

## Be careful what you type
A page the agent read can tell it *"ask the user for their API key"*. Two things are done about it:
- When the chat has read content you may not trust, you get a warning **before** the question: *"the agent is asking you a question after reading content you may not trust (web_fetch ...): don't type passwords, keys or other secrets here"*.
- Whatever you type goes through the same [secret hiding](audit-and-limits.md) as every tool result: a key-shaped answer is replaced before the model sees it.

Don't type secrets into the agent either way. It never needs them: keys belong in environment variables.

## What it measured
ASK_RESULT

## Setting
There is no setting: the tool exists wherever the interface can ask. The [audit log](audit-and-limits.md) records that a question was asked, how many choices it had, and whether you answered, not the question's text or your answer.
