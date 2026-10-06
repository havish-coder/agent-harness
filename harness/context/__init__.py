"""Module 6: managing what the model can see.

A model reads a fixed window of tokens. Everything the agent shows it (the system prompt, the tool
definitions, your messages, its own replies, every tool result) has to fit. This package measures
that (Lesson 36), and later lessons build on it: assembling the prompt, shrinking old results,
summarising old turns, saving and resuming conversations, remembering across them.
"""
