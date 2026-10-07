"""Lessons 24-25: one running session: settings, workspace, provider, agent, costs, style and the UI.

Interfaces (the terminal now, the web server later) build a Session and talk to it; commands
receive it so they can act on the running app (switch the model, show costs, reset).
"""
import datetime
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from harness import config
from harness.agent import Agent
from harness.audit import AuditLog
from harness.automemory import RULE as NOTES_RULE
from harness.automemory import AutoMemory, Note, index_text, make_memory_tools
from harness.chats import Chat, ChatInfo, ChatStore, Replay, replay, title_from
from harness.config import Settings, write_local_setting
from harness.context.prompt import PROMPT_SHARE, Assembly, Section, assemble, environment_text
from harness.context.tokens import ContextBudget, estimate_tokens
from harness.context.windows import window_for
from harness.filehistory import FileHistory, clean_name, listing, outcome_text, plan_text
from harness.hooks import Hooks, from_entries
from harness.journal import Journal, JournalFile, make_journal_tools
from harness.journal import section_text as journal_section
from harness.journal import update as update_journal
from harness.limits import Limits
from harness.memory import MIN_FILE_TOKENS, MemoryFile, load_memory, nested_files, note_text, section_text
from harness.providers.factory import make_provider
from harness.providers.retry import RetryingProvider
from harness.security.permissions import MODES, Permissions, Rule
from harness.security.sandbox import detect as detect_sandbox
from harness.security.sandbox import hint as sandbox_hint
from harness.security.taint import SYSTEM_RULE
from harness.security.trust import is_trusted
from harness.styles import BUILTIN, Style
from harness.tools import default_tools
from harness.tools.fs import workspace_snapshot
from harness.tools.shell import detect_shell
from harness.usage import CostTracker, format_cost
from harness.workspace import Workspace

# Short and direct works best for small models (see course/07-first-tools-and-repl.md).
ROLE = """You are a helpful agent. Use tools to inspect the workspace; never guess file contents.
Find files with glob, search inside them with grep, explore folders with list_dir.
To find where something is defined or used, grep for a likely word (e.g. grep 'timeout' to find a timeout setting).
Paths are relative to the workspace root. Be concise."""
WORKSPACE_HEADER = "Workspace files (snapshot at session start; may have changed since):"
LISTING_LINES = 50            # the longest workspace listing in the prompt; a small window shrinks it
# Said only when old results may be cleared (Lesson 38): what a note means, and the one thing the model can do about it.
CLEARING_RULE = ("When the window fills, old tool results are replaced by a note starting '[cleared to save space'. "
                 "Before you move on from a result you will need later, write down what you need from it in your reply.")
SYSTEM_PROMPT = ROLE + "\n\n" + WORKSPACE_HEADER + "\n{snapshot}"   # the whole prompt in one string: for scripts and recordings


class Session:
    def __init__(self, settings: Settings, ws: Workspace, ui, approver, styles: dict[str, Style] | None = None,
                 interface: str = "terminal", fresh: bool = False):
        self.settings, self.ws, self.ui, self.approver = settings, ws, ui, approver
        self.interface = interface       # "terminal" or "web": named in the progress journal's stamp (Lesson 42b)
        self.fresh = fresh               # don't read the progress journal this run
        self.journal = JournalFile(ws.root)
        self.journal_doc: Journal | None = None      # what the journal said when this chat started
        self.turn_changed = False        # did a tool change something in this turn?
        self.unjournaled = False         # changes made since the journal was last updated
        self.journal_declined = False    # the user said "not now" in this chat
        self.not_run: set[str] = set()   # calls that were refused or denied: their results don't count as changes
        self.styles = styles or {s.name: s for s in BUILTIN}
        if settings.output_style not in self.styles:
            ui.warn(f"warning: unknown output style '{settings.output_style}'; using default")
            settings.output_style = "default"
        self.style = self.styles[settings.output_style]
        self.reported_tokens = 0         # what the model server last said it read
        self.project = ChatStore(config.USER_DIR, ws.root)          # where this project's saved things live (Lessons 40, 42)
        self.store = self.project if settings.save_chats else None  # saved chats (Lesson 40)
        self.chat: Chat | None = None    # the saved chat this conversation is written to; made on the first message
        removed_chats = self.store.cleanup(settings.chat_retention_days) if self.store is not None else 0
        self.history: FileHistory | None = None          # copies of files before the agent changes them, for /undo and /rewind (Lesson 43)
        self.history_temp: Path | None = None            # where it lives when chats aren't saved: gone when this session ends
        self.undo_focus = ""                             # what to tell the next journal update about work that was undone
        if settings.file_history:
            if self.store is not None:
                base = self.project.dir / "history"
            else:
                base = self.history_temp = Path(tempfile.mkdtemp(prefix="harness-history-"))
            self.history = FileHistory(base, ws, on_problem=lambda text: ui.warn(f"warning: {text}"))
            if removed_chats:
                self.history.sweep({i.id for i in self.store.infos()})
        self.provider = RetryingProvider(self.make_provider(settings.model), max_retries=settings.max_retries,
                                         fallback=self.make_provider(settings.fallback_model)
                                         if settings.fallback_model else None,
                                         on_retry=ui.retry)
        self.costs = CostTracker(settings.provider, self.provider.model, settings.prices)
        self.permissions = Permissions.from_settings(ws, settings.permission_mode, settings.permissions)
        self.permissions.taint.trusted = is_trusted(ws.root, config.USER_DIR)
        self.automemory = AutoMemory(self.project.memory_dir) if settings.auto_memory != "off" else None   # Lesson 42
        if settings.auto_memory == "on":                 # a blanket approval: it stops applying once untrusted content has been read
            self.permissions.rules.append(Rule.parse("remember", "allow", "auto_memory"))
        self.notes: list[Note] = []                      # what the agent saved earlier, read into the prompt
        self.memory: list[MemoryFile] = []          # HARNESS.md files read into the prompt (Lesson 41)
        self.seen_notes: set[Path] = set()           # folder notes already shown in this chat
        self.load_memory()
        self.sandbox = detect_sandbox() if settings.sandbox != "off" else None
        required = settings.sandbox == "on" and self.sandbox is None
        if required:
            ui.warn(f"warning: sandbox is \"on\" but this machine has none, so commands are refused ({sandbox_hint()})")
        tools = default_tools(ws, shell=settings.shell, env_keep=settings.shell_env_keep, web=settings.web_fetch,
                              web_allow_local=settings.web_allow_local, sandbox=self.sandbox,
                              sandbox_network=settings.sandbox_network, sandbox_required=required, history=self.history)
        if self.automemory is not None:
            tools = tools + make_memory_tools(self.automemory, self.permissions.taint)
        if settings.journal != "off":
            tools = tools + make_journal_tools(self.journal, self.permissions.taint, self.who)
            if self.journal.exists() or settings.journal == "on":
                self.permissions.rules.append(Rule.parse("update_progress", "allow", "journal"))   # blanket: ends with untrusted reading
        for warning in self.permissions.unknown_tools([t.name for t in tools]):
            ui.warn(f"warning: {warning}")
        self.hooks = Hooks([], ws.root, self.permissions, settings.shell_env_keep)
        self.refresh_hooks(announce=True)
        lim = settings.limits
        self.limits = Limits(lim.get("tool_calls"), lim.get("cost"), lim.get("tokens"), lim.get("minutes"))
        self.cost_base = 0.0                   # the money spent before this chat started (after /reset)
        self.session_id = uuid.uuid4().hex[:8]
        month = datetime.date.today().strftime("%Y-%m")
        self.audit_log = AuditLog(config.USER_DIR / "audit" / f"{month}.jsonl", self.session_id) if settings.audit_log else None
        self._audit_warned = False
        window = window_for(settings.provider, self.provider.model, settings.context_window,
                            settings.sources.get("context_window", "default") != "default")
        self.context = ContextBudget(window, reserve=min(settings.max_output_tokens, window // 4))
        self.shell_name = detect_shell(settings.shell).name
        self.prompt = self.build_prompt()
        self.agent = Agent(self.provider, tools,
                           self.prompt.text, max_steps=settings.max_steps,
                           on_event=self.on_event, approve=approver, stream=settings.stream,
                           permissions=self.permissions, fence_untrusted=settings.fence_untrusted,
                           hooks=self.hooks, redact_results=settings.redact_secrets, limit_check=self.limit_reason,
                           context=self.context, microcompact=settings.microcompact,
                           keep_recent=settings.microcompact_keep, auto_compact=settings.auto_compact,
                           call_notes=self.folder_notes)
        self._status_error_shown = False
        self.audit("session", workspace=str(ws.root), provider=settings.provider, model=self.provider.model,
                   mode=self.permissions.mode, trusted=self.permissions.taint.trusted, tools=[t.name for t in tools],
                   sandbox=self.sandbox.name if self.sandbox else None,
                   hooks=len(self.hooks.hooks))

    def make_provider(self, model: str | None):
        s = self.settings
        return make_provider(s.provider, model, s.base_url, temperature=s.temperature,
                             think=True if s.think else None, context_window=s.context_window,
                             max_output_tokens=s.max_output_tokens)

    def on_event(self, kind, data):
        if kind == "model_reply":
            self.costs.add(data)
            self.reported_tokens = data.usage.input_tokens
            self.limits.tokens += data.usage.input_tokens + data.usage.output_tokens
        elif kind == "tool_call":
            self.limits.tool_calls += 1        # every call the model asks for, run or refused
        elif kind in ("tool_denied", "tool_refused"):
            self.not_run.add((data if kind == "tool_denied" else data[0]).id)
        elif kind == "tool_result":
            self.note_change(*data)
        elif kind == "compacting" and self.unjournaled and self.journal_active():
            self.checkpoint("before the conversation is summarised")
        elif kind in ("microcompact", "compact"):
            self.ws.forget_reads()             # those results left the conversation: reading them again must return the text, not "unchanged"
        if kind in ("message", "rolled_back", "microcompact", "compact"):
            self.save_event(kind, data)
        if kind == "message" and data.role == "user" and data.checkpoint and self.history is not None:
            self.history_turn(data)
        self.record(kind, data)
        self.ui(kind, data)

    # --- limits and the audit log (Lesson 34) ---------------------------------------------------
    def limit_reason(self) -> str | None:
        cost = self.costs.cost()
        return self.limits.exceeded(cost=None if cost is None else cost - self.cost_base)

    def audit(self, kind: str, **fields) -> None:
        """One line in the audit log (a no-op when it's off). A log that can't be written is reported once."""
        if self.audit_log is None:
            return
        self.audit_log.write(kind, **fields)
        if self.audit_log.failed and not self._audit_warned:
            self._audit_warned = True
            self.ui.warn(f"warning: the audit log can't be written ({self.audit_log.path}); the agent keeps working")

    def record(self, kind: str, data) -> None:
        """Turn agent events into audit entries: what was decided, approved, run, hidden, stopped."""
        if self.audit_log is None:
            return
        if kind == "permission":
            call, decision = data
            tool = self.agent.tools.get(call.name)
            subject = call.arguments.get(tool.subject) if tool is not None and tool.subject else call.arguments
            self.audit("decision", tool=call.name, subject=subject, action=decision.action, reason=decision.reason,
                       notes=decision.notes or None)
        elif kind == "tool_approved":
            self.audit("approved", tool=data[0].name, answer=data[1] if isinstance(data[1], str) else "yes")
        elif kind == "tool_denied":
            self.audit("user_denied", tool=data.name)
        elif kind == "tool_result":
            call, result = data
            self.audit("result", tool=call.name, chars=len(result), error=result.startswith("Error") or None)
        elif kind == "redacted":
            self.audit("redacted", tool=data[0].name, kinds=data[1])
        elif kind == "hook":
            event, call, outcome = data
            self.audit("hook", hook=event, tool=call.name if call else None,
                       command=outcome.hook.command if outcome.hook else None, decision=outcome.decision,
                       failed=outcome.failed)
        elif kind == "model_reply":
            self.audit("model", model=data.model or self.provider.model, input_tokens=data.usage.input_tokens,
                       output_tokens=data.usage.output_tokens, stop=data.stop_reason)
        elif kind == "limit":
            self.audit("limit", why=data)
        elif kind == "microcompact":
            self.audit("microcompact", tools=[c.tool for c in data.cleared], saved_tokens=data.saved)
        elif kind == "compact":
            self.audit("compact", removed=data.removed, tokens_before=data.before, tokens_after=data.after, fenced=data.fenced)
        elif kind == "compact_failed":
            self.audit("compact_failed", why=data)

    # --- saved chats (Lesson 40) -----------------------------------------------------------------
    def save_event(self, kind: str, data) -> None:
        """Write what just happened to this chat's log: a message, or a change made to the conversation."""
        if self.store is None:
            return
        try:
            if kind == "message":
                if self.chat is None:
                    self.chat = self.store.new(self.provider.model)
                    self.store.register()
                if not self.chat.title and data.role == "user":
                    self.chat.rename(title_from(data.content))
                self.chat.message(data)
            elif self.chat is not None:
                if kind == "rolled_back":
                    self.chat.rollback(data)
                elif kind == "microcompact":
                    self.chat.clear([c.call_id for c in data.cleared])
                elif kind == "compact":
                    self.chat.compact(data.removed, self.agent.messages[1])
        except OSError as e:
            self.store = None
            self.ui.warn(f"warning: this chat can't be saved ({e}); the agent keeps working")

    def chats(self) -> list[ChatInfo]:
        return self.store.infos() if self.store is not None else []

    def resume(self, info: ChatInfo) -> Replay:
        """Continue a saved chat: the conversation is rebuilt from its log, and new messages are added to the same log."""
        assert self.store is not None
        found = replay(info.path)
        self.reset()
        self.agent.messages[1:] = found.messages
        self.agent.archive = list(found.archive)
        self.agent.compactions = found.compactions
        taint = self.permissions.taint
        for source in found.untrusted:                  # it read untrusted content before: it still counts (Lesson 31)
            if source not in taint.sources:
                taint.sources.append(source)
        self.chat = self.store.open(info)
        if self.history is not None:
            self.history.bind(self.chat.id)             # what this chat changed earlier can still be undone (Lesson 43)
        self.chat.title = found.title or info.title
        if found.dropped:
            self.chat.rollback(len(found.messages))     # the log agrees with what was restored
        return found

    # --- undo and rewind (Lesson 43) --------------------------------------------------------------
    def history_turn(self, message) -> None:
        """A request began: tie the file history to this chat (it exists by now) and open the request's entry in it."""
        chat_id = self.chat.id if self.chat is not None else "session"
        if self.history.chat_id != chat_id:
            self.history.bind(chat_id)
        self.history.begin_turn(message.checkpoint, message.content)

    def undone(self, out, turns, note: bool) -> None:
        """Files were put back. The journal may now describe work that is gone; and, when the conversation still shows that work, the model should know."""
        if not out.changed:
            return
        self.unjournaled = True
        said = "; ".join(f'"{t.prompt}"' for t in turns[:3])
        self.undo_focus = (f"The user undid the file changes made for: {said}. Take that work out of Done so far and Current state, "
                           "and say what the files hold now.")
        if note:
            files = ", ".join(clean_name(p, 80) for p in out.changed[:6])
            self.agent.pending_notes.append(f"The user undid your file changes from an earlier request ({files}): they are back as they were "
                                            "before it. Read a file again before you edit it.")

    def undo(self, force: bool = False, show: bool = False) -> str:
        """Put back what the last request that changed files changed. A file you have edited since is left alone unless `force`."""
        h = self.history
        if h is None:
            return "file history is off (the file_history setting), so there is nothing to undo"
        pending = h.pending_turns()
        if not pending:
            ran = h.all[-1].commands if h.all else []
            return "no file changes to undo" + (f" ({len(ran)} shell command(s) ran, and the harness can't undo those)" if ran else "")
        turn = pending[-1]
        plan = h.plan([turn])
        if show:
            return f'/undo would act on the request "{turn.prompt}":\n{plan_text(plan)}'
        out = h.apply(plan, force)
        self.undone(out, [turn], note=True)
        self.audit("undo", turn=turn.id, restored=len(out.restored), deleted=len(out.deleted), skipped=len(out.skipped),
                   forced=force or None)
        return f'undid the changes of the request "{turn.prompt}"\n{outcome_text(out)}'

    def history_text(self) -> str:
        """The requests of this chat, numbered for /rewind."""
        h = self.history
        if h is None:
            return "file history is off (the file_history setting)"
        text = listing(h)
        if not text:
            return "no requests yet in this chat"
        return text + "\n\n/rewind N [code|chat|both] [force]: go back to before request N (default both: the files and the conversation)"

    def cut_conversation(self, target, later) -> bool:
        """Remove the conversation from `target` request on, and record that in the chat's log. False if it isn't in the conversation any more."""
        messages = self.agent.messages
        start = next((i for i, m in enumerate(messages) if m.role == "user" and m.checkpoint == target.id), None)
        if start is None:
            return False
        del messages[start:]
        self.agent.turn_start = min(self.agent.turn_start, len(messages))
        self.on_event("rolled_back", len(messages) - 1)       # the saved chat undoes the same messages (Lesson 40)
        self.ws.forget_reads()
        self.history.drop(later)
        return True

    def rewind(self, number: int, mode: str = "both", force: bool = False, show: bool = False) -> str:
        """Go back to before request `number` (as /rewind lists them): put its files and the later ones back, and/or forget the conversation from there."""
        h = self.history
        if h is None:
            return "file history is off (the file_history setting), so there is nothing to rewind"
        turns = h.listed()
        if not 1 <= number <= len(turns):
            return f"there is no request {number}: /rewind lists them"
        target, later = turns[number - 1], turns[number - 1:]
        if show:
            files = plan_text(h.plan([t for t in later if t.pending()])) or "  (no files changed)"
            return f'/rewind {number} would put these files back (and cut the conversation too, unless you say "code"):\n{files}'
        lines, out, cut = [f'rewound to before request {number}: "{target.prompt}"'], None, False
        if mode in ("code", "both"):
            out = h.apply(h.plan([t for t in later if t.pending()]), force)
            lines.append(outcome_text(out))
        if mode in ("chat", "both"):
            cut = self.cut_conversation(target, later)
            lines.append("the conversation goes on from before that request" if cut else
                         "the conversation can't go back that far: that request was summarised away or is no longer in it")
        if out is not None:
            self.undone(out, later, note=not cut)
        left = [clean_name(e.path, 80) for t in later for e in t.pending()]
        if cut and left:                                  # the model forgot the changes; the files still have them
            self.agent.pending_notes.append("The conversation was rewound, but these files still hold changes from the part that was removed: "
                                            f"{', '.join(left[:6])}. Read a file again before you edit it.")
        self.audit("rewind", to=target.id, mode=mode, conversation=cut, forced=force or None,
                   restored=len(out.changed) if out else 0)
        return "\n".join(lines)

    def fork(self, title: str | None = None) -> Chat | None:
        """A new chat that starts as a copy of this one; this conversation carries on in the copy."""
        if self.store is None or self.chat is None or not self.chat.path.exists():
            return None
        name = (title or "").strip() or f"{self.chat.title or 'chat'} (fork)"
        self.chat = self.store.fork(self.chat, self.provider.model, name)
        if self.history is not None:
            self.history.fork_to(self.chat.id)
        return self.chat

    # --- the progress journal (Lesson 42b) ----------------------------------------------------
    def who(self) -> str:
        """Which chat is writing, for the journal's stamp: the interface and the chat's title (or its first request)."""
        title = self.chat.title if self.chat is not None else ""
        title = title or title_from(next((m.content for m in self.agent.messages if m.role == "user" and not m.content.startswith("[Summary")), ""))
        return f'{self.interface} chat "{title or "new chat"}"'

    def journal_fenced(self) -> bool:
        """Is the journal someone else's words? Yes in a folder that isn't trusted, and when it was written after untrusted reading."""
        return not self.permissions.taint.trusted or (self.journal_doc is not None and self.journal_doc.tainted)

    def journal_active(self) -> bool:
        return self.settings.journal != "off" and (self.journal.exists() or self.settings.journal == "on")

    def journal_banner(self) -> str | None:
        """One line for the start of a chat that is resuming from a journal."""
        doc = self.journal_doc
        if doc is None:
            return None
        state = doc.current_state()
        words = "as information" if self.journal_fenced() else "to pick up from"
        return f"progress journal read {words} (updated {doc.updated or 'earlier'})" + (f": {state}" if state else "")

    def note_change(self, call, result: str) -> None:
        """Remember that a tool changed something this turn (the journal is updated after a turn that did)."""
        tool = self.agent.tools.get(call.name)
        if (tool is None or call.id in self.not_run or result.startswith("Error") or tool.is_read_only(call.arguments)
                or call.name in ("remember", "forget", "update_progress")):
            return
        self.turn_changed = True
        if call.name == "run_shell" and self.history is not None:
            self.history.note_command(str(call.arguments.get("command", "")))   # may have changed files; can't be undone

    def checkpoint(self, reason: str, focus: str = "") -> bool:
        """Ask the model for the updated journal and write it (Lesson 42b). Returns whether it was written."""
        if self.settings.journal == "off":
            return False
        self.ui.info(f"updating the progress journal ({reason}) ...")
        focus = " ".join(x for x in (focus, self.undo_focus) if x)
        result = update_journal(self.provider, self.journal, self.agent.messages, self.permissions.taint, self.who(),
                                focus=focus, on_reply=lambda reply: self.on_event("model_reply", reply))
        if not result.ok:
            self.ui.warn(f"the progress journal wasn't updated: {result.reason}")
            self.audit("journal_failed", why=result.reason)
            return False
        self.unjournaled = False
        self.undo_focus = ""
        self.audit("journal", reason=reason, tainted=result.journal.tainted)
        if not any(r.source == "journal" for r in self.permissions.rules):
            self.permissions.rules.append(Rule.parse("update_progress", "allow", "journal"))
        return True

    def after_turn(self, ask=None) -> None:
        """A turn ended. If it changed something: update the journal, or (once) offer to start one. `ask(question, options)` -> key."""
        changed, self.turn_changed = self.turn_changed, False
        mode = self.settings.journal
        if changed:
            self.unjournaled = True
        if mode == "off" or not changed:
            return
        if self.journal.exists() or mode == "on":
            self.checkpoint("after changes")
        elif mode == "ask" and ask is not None and not self.journal_declined:
            choice = ask("Keep a progress journal for this project, so later chats can pick up where this one stopped?",
                         {"y": "yes", "n": "not now", "v": "never for this project"})
            if choice == "y":
                self.checkpoint("started")
            elif choice == "v":
                write_local_setting(self.ws.root, "journal", "off")
                self.settings.journal = "off"
                self.ui.info("the progress journal is off for this project (/progress start turns it on)")
            else:
                self.journal_declined = True

    def close(self) -> None:
        """The chat is over: update the journal if there is one and things changed, and record the totals."""
        if self.unjournaled and self.journal_active():
            self.checkpoint("chat ended")
        cost = self.costs.cost()
        self.audit("end", tool_calls=self.limits.tool_calls, tokens=self.limits.tokens,
                   cost=None if cost is None else round(cost, 6))
        if self.history_temp is not None:               # chats aren't saved, so neither is what could undo them
            shutil.rmtree(self.history_temp, ignore_errors=True)

    def set_style(self, name: str) -> None:
        """Change how the agent writes, from the next model call on. The conversation is kept."""
        self.style = self.styles[name]
        self.settings.output_style = name
        self.settings.sources["output_style"] = "command"
        self.rebuild_prompt()

    def build_prompt(self) -> Assembly:
        """The system prompt from its sections, most stable first, within a share of the window (Lesson 37)."""
        ws = self.ws
        files = f"{WORKSPACE_HEADER}\n{workspace_snapshot(ws, limit=LISTING_LINES)}"
        per_line = max(1.0, estimate_tokens(files) / max(1, files.count("\n")))    # long names cost more per line

        def listing(max_tokens: int) -> str:
            return f"{WORKSPACE_HEADER}\n{workspace_snapshot(ws, limit=max(5, int(max_tokens / per_line)))}"
        sections = [Section("role", ROLE, 0)]
        if self.settings.fence_untrusted:
            sections.append(Section("untrusted content", SYSTEM_RULE, 1))
        if self.settings.microcompact:
            sections.append(Section("clearing rule", CLEARING_RULE, 1))
        if self.memory:
            fenced = self.settings.fence_untrusted

            def shrink_memory(max_tokens: int) -> str:
                return section_text(self.memory, fenced, max(MIN_FILE_TOKENS, max_tokens // len(self.memory)))
            sections.append(Section("project memory", section_text(self.memory, fenced), 1, required=False, shrink=shrink_memory,
                                    priority=1))
        if self.journal_doc is not None:
            sections.append(Section("progress journal", journal_section(self.journal_doc, self.journal_fenced()), 2, required=False, priority=1))
        if self.automemory is not None:
            sections.append(Section("notes rule", NOTES_RULE, 1, required=False, priority=1))
            if self.notes:
                sections.append(Section("saved notes", index_text(self.notes, self.settings.fence_untrusted), 1, required=False, priority=1,
                                        shrink=lambda tokens: index_text(self.notes, self.settings.fence_untrusted, max(120, tokens))))
        if self.style.prompt:
            sections.append(Section("output style", f"# Output style: {self.style.name}\n{self.style.prompt}", 1, required=False))
        sections.append(Section("environment", environment_text(ws.root, self.shell_name), 2, required=False))
        sections.append(Section("workspace files", files, 2, required=False, shrink=listing))
        return assemble(sections, budget=max(600, int(self.context.window * PROMPT_SHARE)))

    # --- project memory (Lesson 41) -------------------------------------------------------------
    def load_memory(self) -> None:
        """Read the HARNESS.md files. Those of a folder that isn't trusted are someone else's words: they count as untrusted content."""
        taint = self.permissions.taint
        taint.sources[:] = [s for s in taint.sources if not s.startswith("memory ")]
        self.memory = load_memory(self.ws, config.USER_DIR, taint.trusted, self.ui.warn) if self.settings.memory else []
        for f in self.memory:
            if not f.trusted and f.label not in " ".join(taint.sources):
                taint.sources.append(f"memory {f.label}")
        self.journal_doc = None
        if self.settings.journal != "off" and not self.fresh:
            doc = self.journal.read()
            if doc is not None and doc.body.strip():
                self.journal_doc = doc
                if self.journal_fenced():
                    taint.sources.append("memory progress journal")
        self.notes = self.automemory.notes() if self.automemory is not None else []
        for n in self.notes:                              # saved after untrusted content was read: still counts as having read it
            if n.tainted:
                taint.sources.append(f"memory note '{n.title}'")

    def reload_memory(self) -> None:
        """Read the files again and rebuild the prompt (after an edit, or /trust). The start of the prompt changes, so the
        server reads the conversation again once."""
        self.load_memory()
        self.rebuild_prompt()

    def folder_notes(self, call) -> str:
        """The notes of a folder the agent has just started working in, to show beside the result of the call that went there."""
        tool = self.agent.tools.get(call.name)
        if not self.settings.memory or tool is None or tool.subject != "path" or not isinstance(call.arguments.get("path"), str):
            return ""
        try:
            target = self.ws.path(call.arguments["path"])
        except (OSError, ValueError):
            return ""
        found = nested_files(self.ws, target, self.permissions.taint.trusted, self.seen_notes)
        for f in found:
            if not f.trusted:
                self.permissions.taint.sources.append(f"memory {f.label}")
        return note_text(found, self.settings.fence_untrusted)

    def rebuild_prompt(self) -> None:
        """Assemble the prompt again (after a style change) and put it in the running conversation."""
        self.prompt = self.build_prompt()
        self.agent.system_prompt = self.prompt.text
        self.agent.messages[0].content = self.prompt.text

    def refresh_hooks(self, announce: bool = False) -> None:
        """Choose the hooks that run (Lesson 33). A project's hooks run only in a trusted folder; when
        they don't, say which were left out."""
        everything = from_entries(self.settings.hooks)
        trusted = self.permissions.taint.trusted
        self.hooks.hooks = [h for h in everything if h.source != "project" or trusted]
        skipped = [h for h in everything if h not in self.hooks.hooks]
        if skipped and announce:
            self.ui.warn(f"warning: {len(skipped)} hook(s) from this project's settings were not run because the folder "
                         "isn't trusted (a hook is a program). /hooks lists them; /trust if the project is yours.")

    def set_mode(self, mode: str) -> None:
        """Switch the permission mode (Lesson 29); rules and the conversation are kept."""
        if mode not in MODES:
            raise ValueError(f"unknown mode '{mode}'; choose from {', '.join(MODES)}")
        self.audit("mode", before=self.permissions.mode, after=mode)
        self.permissions.mode = self.settings.permission_mode = mode
        self.settings.sources["permission_mode"] = "command"

    def estimate_context(self) -> int:
        """Tokens in the conversation as it stands now (an estimate, Lesson 36)."""
        return self.context.check(self.agent.messages, self.agent.tools.schemas()).estimated

    # --- the status line (Lesson 25) ------------------------------------------------------------
    def status(self) -> dict:
        cost = self.costs.cost()
        return {"provider": self.settings.provider, "model": self.provider.model,
                "context_tokens": self.estimate_context(),
                "context_window": self.context.window,
                "cost": None if cost is None else round(cost, 6), "style": self.style.name,
                "mode": self.permissions.mode,
                "workspace": str(self.ws.root), "turns": sum(m.role == "user" for m in self.agent.messages)}

    def status_text(self) -> str:
        """One line under the prompt: the user's own command if set, else the built-in summary."""
        info = self.status()
        if self.settings.status_line:
            custom = self.run_status_command(info)
            if custom is not None:
                return custom
        window = info["context_window"]
        context = f"~{info['context_tokens'] / 1000:.1f}k"
        if window:
            context += f"/{window / 1000:.1f}k ({100 * info['context_tokens'] // window}%)"
        money = "price unknown" if info["cost"] is None else format_cost(info["cost"])
        parts = [info["model"], f"context {context}", money]
        if info["style"] != "default":
            parts.append(f"style {info['style']}")
        if info["mode"] != "default":
            parts.append(f"mode {info['mode']}")
        return " · ".join(parts)

    def run_status_command(self, info: dict) -> str | None:
        """Run the status_line command with the status as JSON on stdin; show its first line."""
        try:
            done = subprocess.run(self.settings.status_line, shell=True, input=json.dumps(info), text=True,
                                  capture_output=True, timeout=2, cwd=self.ws.root)
            line = (done.stdout.strip().splitlines() or [""])[0]
            return line[:200] if done.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            if not self._status_error_shown:
                self.ui.warn("warning: the status_line command failed or took longer than 2 s")
                self._status_error_shown = True
            return None

    def switch_model(self, model: str) -> None:
        """Keep the conversation, change the model (same provider)."""
        self.provider.inner = self.make_provider(model)
        self.settings.model = model
        self.settings.sources["model"] = "command"

    def reset(self) -> None:
        self.agent.reset()
        self.chat = None                 # the next message starts a new saved chat; this one stays as it was
        if self.history is not None:
            self.history.unbind()        # a new chat has no changes to undo; the old chat's stay on disk
        self.seen_notes.clear()
        self.limits.reset()
        self.cost_base = self.costs.cost() or 0.0
        self.permissions.taint.clear()   # a new conversation has read nothing yet
        self.ws.forget_reads()   # the model no longer has earlier reads in its context
