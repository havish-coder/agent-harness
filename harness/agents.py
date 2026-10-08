"""Lesson 47: sub-agents. Give a job to a fresh agent, and get back only its report.

The agent's context window is the scarcest thing it has (Lesson 36). A question like "where is the retry logic, and how does it work?" can mean fifteen file
reads, and every one of them stays in the conversation for the rest of the chat. A **sub-agent** does that reading in a conversation of its own and hands back
a few lines. The parent's window pays for the report, not for the reading.

    delegate(agent="explore", task="Where do we apply tax, and to what? Name the files and functions.")
        -> a fresh Agent, its own messages and its own window, read-only tools, up to 14 steps
        -> returns its final answer (cut to 4,000 characters) and a footer: "(explore: 7 tool calls, ~9,100 tokens, 31 s)"

What is shared, and what isn't, decides whether this is safe:

  shared:   the **permissions** (mode, rules, and the taint record), the approver, the hooks, the session's limits and cost, the file history, the workspace.
            So a sub-agent can never do what its parent couldn't: in plan mode its edits are refused too; an edit asks the same way; a `pre_tool_use` hook sees its calls;
            what it reads from an untrusted source taints the whole session; what it spends counts against the same limits.
  its own:  the conversation, the system prompt (the definition's text, the untrusted-content rule, project memory, a short workspace listing), the context window, the step limit.
  not given: `delegate` itself (a sub-agent can't start sub-agents: depth is one), and the tools that talk to the user or write down state for later: `ask_user`, `exit_plan_mode`,
            `todo_write`, `remember`, `forget`, `update_progress`.

The report is model-written text derived from whatever the sub-agent read. If it read anything untrusted (the taint record grew while it ran) the report is fenced as untrusted
when it comes back, so the parent treats it as information and not as instructions.

Definitions are Markdown files with a header, like commands (Lesson 24):

    ---
    name: reviewer
    description: Reads a change and lists what could go wrong. Cannot edit.
    tools: read-only            # read-only | all | read_file, grep, glob
    max_steps: 10
    model: inherit              # or a model name, for a cheaper one
    ---
    You review code. Read what you are given, then list ...

Built-ins (`explore`, `worker`) come first; yours are `~/.harness/agents/*.md`; a project's are `<workspace>/.harness/agents/*.md`, read **only in a folder you trust** (a definition is
instructions for a model, and a cloned repository must not get to write them), and can't replace a built-in.
"""
import re
from dataclasses import dataclass, replace
from pathlib import Path

from harness.commands import NAME, parse_frontmatter
from harness.tools.base import Tool, tool

MAX_REPORT_CHARS = 4_000
MAX_TASK_CHARS = 2_000
MAX_STEPS = 30
# Never given to a sub-agent: starting more, talking to the user, and writing down state for later chats.
EXCLUDED = frozenset({"delegate", "ask_user", "exit_plan_mode", "todo_write", "remember", "forget", "update_progress"})
SUBAGENT_RULE = ("When a question needs many files read (where something is used, how a feature works), give it to a sub-agent: "
                 "delegate(agent='explore', task='...') returns a short report and keeps your own conversation small.")

EXPLORE_PROMPT = ("You are an explorer. You are given a question about a project. Find the answer by reading and searching (list_dir, glob, grep, read_file), "
                  "then report. Be thorough about where to look and brief in what you say: lead with the answer, then the file paths and line numbers that "
                  "support it. You cannot change anything. Do not guess: if you didn't find it, say what you looked at.")
WORKER_PROMPT = ("You are given one self-contained job by another agent. Do it with the tools you have, check your work, and report briefly: what you changed (file paths), "
                 "what you ran and what it showed, and anything you could not do. Stay within the job.")


@dataclass
class AgentDef:
    name: str
    description: str
    prompt: str
    tools: str = "read-only"           # "read-only", "all", or a comma-separated list of tool names
    max_steps: int = 12
    model: str = "inherit"
    source: str = "built-in"           # built-in, user or project

    def tool_names(self, available: list[Tool]) -> list[str]:
        """Which of the parent's tools this definition may use, never an excluded one."""
        usable = [t for t in available if t.name not in EXCLUDED]
        spec = self.tools.strip().lower()
        if spec in ("", "read-only", "readonly"):
            return [t.name for t in usable if t.read_only is True]       # statically read-only: a flag that depends on the arguments (the shell) doesn't count
        if spec == "all":
            return [t.name for t in usable]
        wanted = [w.strip() for w in re.split(r"[,\s]+", self.tools) if w.strip()]
        have = {t.name for t in usable}
        return [w for w in wanted if w in have]

    @property
    def read_only(self) -> bool:
        return self.tools.strip().lower() in ("", "read-only", "readonly")


BUILTIN = [
    AgentDef("explore", "reads and searches the project, reports; cannot change anything", EXPLORE_PROMPT, "read-only", 14),
    AgentDef("worker", "does one self-contained job with your tools", WORKER_PROMPT, "all", 20),
]


def load_agents(workspace: Path, user_dir: Path, trusted: bool) -> tuple[dict[str, AgentDef], list[str]]:
    """Built-ins, then the user's definitions, then (in a trusted folder) the project's. Returns (definitions, warnings)."""
    found = {a.name: replace(a) for a in BUILTIN}          # copies: a session changing one must not change them for the next
    warnings: list[str] = []
    for folder, source in ((Path(user_dir) / "agents", "user"), (Path(workspace) / ".harness" / "agents", "project")):
        if not folder.is_dir():
            continue
        files = sorted(folder.glob("*.md"))
        if source == "project" and not trusted:
            if files:
                warnings.append(f"{len(files)} agent definition(s) in {folder} were not read: this folder isn't trusted (/trust if you wrote them)")
            continue
        for path in files:
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            name = (meta.get("name") or path.stem).lower()
            if not NAME.match(name):
                warnings.append(f"{path}: agent names use a-z, 0-9 and '-'; skipped")
                continue
            if source == "project" and name in found and found[name].source == "built-in":
                warnings.append(f"{path}: a project can't replace the built-in agent '{name}'; skipped")
                continue
            if not body.strip():
                warnings.append(f"{path}: empty agent; skipped")
                continue
            try:
                steps = max(1, min(MAX_STEPS, int(meta.get("max_steps", 12))))
            except ValueError:
                warnings.append(f"{path}: max_steps isn't a number; using 12")
                steps = 12
            found[name] = AgentDef(name, meta.get("description", f"custom agent from {path.name}"), body.strip(), meta.get("tools", "read-only"),
                                   steps, meta.get("model", "inherit") or "inherit", source)
    return found, warnings


def agents_text(agents: dict[str, AgentDef]) -> str:
    return "\n".join(f"- {a.name}: {a.description}" + ("" if a.source == "built-in" else f" ({a.source})") for a in agents.values())


def make_agent_tools(run, agents: dict[str, AgentDef]) -> list[Tool]:
    """`delegate(agent, task)`. `run(agent_name, task)` (the session's) does the work and returns the text for the model.

    Read-only as far as permissions go, whatever the sub-agent can do: every call *it* makes goes through the same permission layer as the parent's,
    so a delegate in plan mode can read and nothing more, and one that edits asks as the parent would. Asking again for the delegation itself would be a second question about
    one thing."""

    @tool(read_only=True, concurrency_safe=False)
    def delegate(agent: str, task: str) -> str:
        """Give a job to a sub-agent with its own conversation; you get back only its report. It can't see your conversation: put everything in the task.

        Args:
            agent: which one (listed below).
            task: the job or question, complete in itself.
        """
        return run(agent, task)

    delegate.description = delegate.description + "\n\nAgents:\n" + agents_text(agents)
    return [delegate]
