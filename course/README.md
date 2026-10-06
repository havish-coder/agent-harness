# Build an Agent Harness from Scratch

A hands-on course. By the end you will have built, from nothing, a working AI agent
harness (the same kind of software as Claude Code, Codex CLI or Cursor's agent), turned
it into a secure web product, and extended it for a task of your choice.

**Rules of the course**
- Python 3.10. **No agent frameworks** (no LangChain, LlamaIndex, CrewAI...). If a
  harness does something, we write it, so you can see exactly how it works.
- Local model first (Ollama + `qwen3:4b-instruct`). The design lets a cloud API plug in later.
- Security is a core module, not an afterthought.

---

## How each lesson works

Every lesson follows the same four steps:

| Step | What happens | Where |
|---|---|---|
| **1. Learn** | Concept explained in plain language, with diagrams and how real harnesses do it | `course/NN-topic.md` |
| **2. Build** | The code for this lesson, written in small explained steps | the repo (one git commit per lesson) |
| **3. Understand** | Code walkthrough + **experiments**: run it, change it, break it on purpose | "Experiments" section of the lesson |
| **4. Review** | Quiz (answers at the bottom), optional exercise, checkpoint demo | "Review" section of the lesson |

Finish a lesson, try the experiments and quiz, ask questions, then say **"next"**.

### Moving through the code history
Every lesson is tagged in git, so you can see exactly what each lesson added:

```bash
git tag                          # list all lessons
git diff lesson-05 lesson-06     # what lesson 06 added
git checkout lesson-04           # go back in time (git checkout main to return)
```

---

## Syllabus & progress

### Module 0: Foundations
- [ ] 00 · [What is an agent harness](00-what-is-an-agent-harness.md)
- [ ] 01 · [LLMs as an API](01-llms-as-an-api.md): tokens, context, roles, sampling, plus setup
- [ ] 02 · [Talking to the raw API](02-talking-to-the-raw-api.md)
- [ ] 03 · [Tool calling on the wire](03-tool-calling-on-the-wire.md)

### Module 1: The Agent Loop
- [ ] 04 · [Message model](04-message-model.md)
- [ ] 05 · [Provider adapter](05-provider-adapter.md)
- [ ] 06 · [The loop](06-the-loop.md)
- [ ] 07 · [First tools + REPL](07-first-tools-and-repl.md)

### Lessons 08 and later
The course continues privately from Lesson 08. The **code keeps landing in this repo**, one
commit per lesson, tagged `lesson-NN`, with a release per module (`v0.2` … `v1.0`), so you can
still follow the product's history with `git tag` and `git diff`.

For what the product does today, see the [README](../README.md), the
[documentation](../docs/index.md) and the [changelog](../CHANGELOG.md).
