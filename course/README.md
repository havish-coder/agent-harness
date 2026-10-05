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
- [ ] 02 · Talking to the raw API
- [ ] 03 · Tool calling on the wire

### Module 1: The Agent Loop
- [ ] 04 · Message model
- [ ] 05 · Provider adapter
- [ ] 06 · The loop
- [ ] 07 · First tools + REPL

### Module 2: The Tool System
- [ ] 08 · Schemas from code (`@tool` decorator)
- [ ] 09 · Registry, validation & errors
- [ ] 10 · File editing tools
- [ ] 11 · Shell tool (naive, hardened later)
- [ ] 12 · Streaming UX
- [ ] 13 · Testing agents (FakeProvider)

### Module 3: Providers & Config
- [ ] 14 · A second provider (OpenAI-compatible)
- [ ] 15 · Config & secrets

### Module 4: Security
- [ ] 16 · Threat modeling
- [ ] 17 · Attack lab (before): break our own agent
- [ ] 18 · Sandbox: path jail
- [ ] 19 · Permissions & human approval
- [ ] 20 · Shell hardening
- [ ] 21 · Prompt injection & taint tracking
- [ ] 22 · Network & SSRF
- [ ] 23 · Limits: loops, budgets, timeouts
- [ ] 24 · Audit log & secret redaction
- [ ] 25 · Attack lab (after): prove the defenses

### Module 5: Context & Memory
- [ ] 26 · Token accounting
- [ ] 27 · Compaction
- [ ] 28 · Sessions
- [ ] 29 · Project memory (`AGENT.md`)
- [ ] 30 · Slash commands

### Module 6: The Web Product
- [ ] 31 · Server & streaming
- [ ] 32 · Chat UI
- [ ] 33 · Approvals in the browser
- [ ] 34 · Connect your LLM (Ollama or API)
- [ ] 35 · Web security

### Module 7: Capstone
- [ ] 36 · Pick the domain
- [ ] 37+ · Domain features (planning, sub-agents, specialized tools, evals)
