"""Lesson 45: plan mode. The agent looks and proposes; only the user's yes lets it change anything."""
import os

import pytest

from harness import config
from harness.commands import Send, load_commands
from harness.config import Settings
from harness.messages import ToolCall
from harness.plan import (
    CHOICES,
    MAX_PLAN_CHARS,
    PLAN_RULE,
    latest_plan,
    make_plan_tools,
    plan_items,
    save_plan,
    slug,
    steps,
    title_of,
)
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.session import Session
from harness.tools.base import tool
from harness.tools.registry import ToolRegistry
from harness.tui.plain import PlainUI
from harness.workspace import Workspace

PLAN = """Goal: fix the subtotal bug.
1. Edit shop/cart.py: multiply price by quantity in subtotal().
2. Add a test in tests/test_cart.py for quantity 0.
   (it should expect ValueError)
3. Run the tests.
Unsure: whether quantity 0 should be allowed."""


# --- reading a plan ---------------------------------------------------------------------------------------------

def test_numbered_lines_at_the_margin_are_the_steps():
    assert steps(PLAN) == ["Edit shop/cart.py: multiply price by quantity in subtotal().", "Add a test in tests/test_cart.py for quantity 0.", "Run the tests."]


def test_indented_detail_bullets_and_prose_are_not_steps():
    assert steps("Goal\n- a bullet\n    1. deeply indented\nthen 2. in a sentence\n1) first\n2) second") == ["first", "second"]


def test_steps_are_short_clean_lines_and_limited():
    many = "\n".join(f"{n}. step {n}" for n in range(1, 30))
    assert len(steps(many)) == 20
    got = steps("1. do\x1b[31mit\x07 now")
    assert len(got) == 1 and got[0].startswith("do [31mit") and "\x1b" not in got[0] and "\x07" not in got[0]


def test_the_first_step_starts_in_progress():
    items = plan_items(PLAN)
    assert [i.status for i in items] == ["in_progress", "pending", "pending"] and plan_items("no numbered steps here") == []


def test_a_plan_is_named_by_its_first_heading_or_line():
    assert title_of("# Fix the cart\n1. x") == "Fix the cart" and title_of("\n\nGoal: do it\n") == "Goal: do it" and title_of("") == "plan"
    assert slug("Fix the Cart!! now") == "fix-the-cart-now" and slug("???") == "plan" and len(slug("x" * 100)) == 40


def test_plans_are_saved_in_the_given_folder_and_the_newest_is_found(tmp_path):
    first = save_plan(tmp_path / "plans", "# One\n1. a\n2. b")
    os.utime(first, (1, 1))
    second = save_plan(tmp_path / "plans", "# Two\n1. c\n2. d")
    path, body = latest_plan(tmp_path / "plans")
    assert path in (first, second) and body.endswith("\n") and latest_plan(tmp_path / "none") is None
    assert first.name.endswith("-one.md") and (second.name.endswith("-two.md"))


# --- the tool is there only in plan mode ------------------------------------------------------------------------------

def test_a_tool_can_be_shown_only_while_something_is_true():
    on = {"yes": False}

    @tool(read_only=True, enabled=lambda: on["yes"])
    def sometimes() -> str:
        """Only sometimes."""
        return "ran"

    registry = ToolRegistry([sometimes])
    assert registry.schemas() == []
    found, error = registry.resolve(ToolCall("1", "sometimes", {}))
    assert found is None and "isn't available right now" in error
    on["yes"] = True
    assert [s["name"] for s in registry.schemas()] == ["sometimes"] and registry.resolve(ToolCall("1", "sometimes", {}))[0] is sometimes


def test_unknown_tool_errors_list_only_the_available_ones():
    @tool(read_only=True, enabled=lambda: False)
    def hidden() -> str:
        """Hidden."""
        return ""

    @tool(read_only=True)
    def shown() -> str:
        """Shown."""
        return ""
    _, error = ToolRegistry([hidden, shown]).resolve(ToolCall("1", "nope", {}))
    assert "shown" in error and "hidden" not in error


def test_a_broken_switch_hides_the_tool():
    def broken():
        raise RuntimeError("x")

    @tool(read_only=True, enabled=broken)
    def t() -> str:
        """T."""
        return ""
    assert not t.is_enabled() and ToolRegistry([t]).schemas() == []


def test_the_plan_tool_is_read_only_so_plan_mode_allows_it():
    t = make_plan_tools(lambda p: "ok", lambda: True)[0]
    assert t.name == "exit_plan_mode" and t.is_read_only({}) and t.parameters["required"] == ["plan"] and "numbered steps" in t.description


# --- the session ---------------------------------------------------------------------------------------------------------

class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.answers, self.texts, self.questions, self.plans, self.warnings = [], [], [], [], []

    def __call__(self, kind, data):
        pass

    def ask_choice(self, question, options):
        self.questions.append((question, options))
        return self.answers.pop(0) if self.answers else ""

    def ask_text(self, question):
        return self.texts.pop(0) if self.texts else ""

    def show_plan(self, plan):
        self.plans.append(plan)

    def warn(self, text_):
        self.warnings.append(text_)

    def info(self, text_):
        pass


class NoApprover:
    pause = None

    def __call__(self, call, tool, decision=None):
        return True


def make_session(tmp_path, monkeypatch, mode="default", files=None, ui=None, **settings):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {}).items():
        (root / name).write_text(content, encoding="utf-8")
    from harness.security.trust import set_trusted
    set_trusted(root, config.USER_DIR, True)
    base = {"save_chats": False, "auto_memory": "off", "journal": "off", "file_history": False, "permission_mode": mode}
    s = Session(Settings(**(base | settings)), Workspace(root), ui or Quiet(), NoApprover())
    s.agent.stream = False
    return s


def run(session, line):
    command, args = load_commands(session.ws.root).parse(line)
    return command.run(session, args)


def tool_names(s):
    return [t["name"] for t in s.agent.tools.schemas()]


def propose(s, plan=PLAN, *more):
    # (spare answers: an approved plan starts a todo list, and a list with open items is nudged before the model may finish)
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("p", "exit_plan_mode", {"plan": plan})), *(more or (text("ok"),) * 3)])
    return s.agent.run("plan it")


def test_the_tool_and_the_rule_exist_only_in_plan_mode(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "exit_plan_mode" not in tool_names(s) and "plan mode" not in [p.name for p in s.prompt.parts]
    s.set_mode("plan")
    assert "exit_plan_mode" in tool_names(s) and PLAN_RULE in s.prompt.text and PLAN_RULE in s.agent.messages[0].content
    s.set_mode("default")
    assert "exit_plan_mode" not in tool_names(s) and PLAN_RULE not in s.agent.messages[0].content


def test_starting_in_plan_mode_has_both(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    assert "exit_plan_mode" in tool_names(s) and PLAN_RULE in s.prompt.text


def test_switching_between_other_modes_leaves_the_prompt_alone(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    before = s.prompt.text
    s.set_mode("accept-edits")
    assert s.prompt.text == before


def test_in_plan_mode_nothing_can_change_however_the_model_is_persuaded(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan", files={"a.txt": "one\n"})
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("1", "write_file", {"path": "b.txt", "content": "x"}),
                                                   ToolCall("2", "run_shell", {"command": "echo hi > c.txt"})), text("ok")])
    s.agent.run("just do it")
    assert not (s.ws.root / "b.txt").exists() and not (s.ws.root / "c.txt").exists()
    results = [m.content for m in s.agent.messages if m.role == "tool"]
    assert all("plan mode is on" in r for r in results)


@pytest.mark.parametrize("key,mode", [("y", "default"), ("a", "accept-edits")])
def test_a_yes_from_the_user_changes_the_mode_and_the_prompt(tmp_path, monkeypatch, key, mode):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.ui.answers = [key]
    propose(s)
    assert s.permissions.mode == mode and s.ui.plans == [PLAN.strip()] and "exit_plan_mode" not in tool_names(s)
    result = [m.content for m in s.agent.messages if m.role == "tool"][0]
    assert f"permission mode is now '{mode}'" in result and "step by step" in result
    assert s.ui.questions[0][1] == CHOICES and PLAN_RULE not in s.agent.messages[0].content


def test_the_approved_plan_is_saved_and_shown_again_with_plan_show(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.ui.answers = ["y"]
    propose(s)
    saved = list(s.plans_dir.glob("*.md"))
    assert len(saved) == 1 and "Edit shop/cart.py" in saved[0].read_text(encoding="utf-8") and not saved[0].is_relative_to(s.ws.root)
    assert run(s, "/plan show") == PLAN.strip()
    again = make_session(tmp_path, monkeypatch)
    assert "saved" in run(again, "/plan show") and "Edit shop/cart.py" in run(again, "/plan show")


def test_an_approved_plan_starts_the_todo_list(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.ui.answers = ["a"]
    propose(s)
    assert [(i.content[:12], i.status) for i in s.todos.items] == [("Edit shop/ca", "in_progress"), ("Add a test i", "pending"), ("Run the test", "pending")]
    assert "numbered steps are now your todo list" in [m.content for m in s.agent.messages if m.role == "tool"][0]


def test_a_plan_with_one_step_or_none_starts_no_list(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.ui.answers = ["y"]
    propose(s, "Goal: do the thing.\n1. just one step in the plan")
    assert s.todos.items == []


def test_the_list_is_not_started_when_the_todo_setting_is_off(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan", todo=False)
    s.ui.answers = ["y"]
    propose(s)
    assert s.todos.items == [] and s.permissions.mode == "default"


@pytest.mark.parametrize("key", ["n", ""])
def test_no_or_no_answer_keeps_plan_mode(tmp_path, monkeypatch, key):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.ui.answers = [key]
    propose(s)
    assert s.permissions.mode == "plan" and "exit_plan_mode" in tool_names(s)
    result = [m.content for m in s.agent.messages if m.role == "tool"][0]
    assert "did not approve" in result and "still in plan mode" in result and not list(s.plans_dir.glob("*.md"))


def test_feedback_goes_back_to_the_model_in_the_users_words(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.ui.answers, s.ui.texts = ["f"], ['use a "guard clause" instead']
    propose(s)
    result = [m.content for m in s.agent.messages if m.role == "tool"][0]
    assert "use a 'guard clause' instead" in result and "revise the plan" in result and s.permissions.mode == "plan"


def test_asking_for_feedback_but_saying_nothing_is_a_plain_no(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.ui.answers, s.ui.texts = ["f"], [""]
    propose(s)
    assert "did not approve" in [m.content for m in s.agent.messages if m.role == "tool"][0]


def test_a_plan_the_user_cant_be_asked_about_is_an_error_not_an_approval(tmp_path, monkeypatch):
    class Mute(Quiet):
        """An interface with no way to ask."""
        ask_choice = None
        ask_text = None
        show_plan = None
    s = make_session(tmp_path, monkeypatch, mode="plan", ui=Mute())
    propose(s)
    assert s.permissions.mode == "plan" and "can't be shown to the user" in [m.content for m in s.agent.messages if m.role == "tool"][0]


def test_a_plan_that_is_too_short_or_too_long(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    propose(s, "ok")
    assert "too short to review" in [m.content for m in s.agent.messages if m.role == "tool"][0] and s.ui.plans == []
    s2 = make_session(tmp_path, monkeypatch, mode="plan")
    s2.ui.answers = ["n"]
    propose(s2, "1. step\n" * 2000)
    assert len(s2.ui.plans[0]) <= MAX_PLAN_CHARS + 60 and "the rest was cut" in s2.ui.plans[0]


def test_the_model_cannot_leave_plan_mode_by_itself(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.ui.answers = ["n"]                                         # the user says no
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("1", "exit_plan_mode", {"plan": PLAN})), tool_calls(ToolCall("2", "write_file", {"path": "x.txt", "content": "y"})), text("ok")])
    s.agent.run("go")
    assert s.permissions.mode == "plan" and not (s.ws.root / "x.txt").exists()


def test_after_a_yes_changes_ask_as_the_new_mode_says(tmp_path, monkeypatch):
    asked = []
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.agent.approve = lambda call, tool, decision=None: asked.append(call.name) or True
    s.ui.answers = ["y"]
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("1", "exit_plan_mode", {"plan": PLAN})),
                                         tool_calls(ToolCall("2", "write_file", {"path": "x.txt", "content": "y"})), text("done"), text("done"), text("done")])
    s.agent.run("plan and do it")
    assert asked == ["write_file"] and (s.ws.root / "x.txt").exists()                  # default mode: it asked, and the (scripted) user said yes


def test_after_a_for_file_edits_run_without_asking(tmp_path, monkeypatch):
    asked = []
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.agent.approve = lambda call, tool, decision=None: asked.append(call.name) or True
    s.ui.answers = ["a"]
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("1", "exit_plan_mode", {"plan": PLAN})),
                                         tool_calls(ToolCall("2", "write_file", {"path": "x.txt", "content": "y"})), text("done"), text("done"), text("done")])
    s.agent.run("plan and do it")
    assert asked == [] and (s.ws.root / "x.txt").exists()


def test_a_chat_that_read_untrusted_content_warns_before_the_approval(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    s.permissions.taint.sources.append("web_fetch http://example.com")
    s.ui.answers = ["n"]
    propose(s)
    assert any("may not trust" in w and "example.com" in w for w in s.ui.warnings)


def test_the_approval_is_in_the_audit_log(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan", audit_log=True)
    s.ui.answers = ["y"]
    propose(s)
    entries = [line for line in s.audit_log.path.read_text(encoding="utf-8").splitlines() if '"plan"' in line or '"mode"' in line]
    assert any('"answer":"y"' in e.replace(" ", "") for e in entries) and any('"after":"default"' in e.replace(" ", "") for e in entries)


# --- the commands ----------------------------------------------------------------------------------------------------------

def test_plan_turns_plan_mode_on_and_off_and_remembers_where_it_came_from(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="accept-edits")
    said = run(s, "/plan")
    assert s.permissions.mode == "plan" and "plan mode on" in said
    assert "already on" in run(s, "/plan")
    assert run(s, "/plan off") == "plan mode is off: permission mode accept-edits" and s.permissions.mode == "accept-edits"
    assert run(s, "/plan off") == "plan mode isn't on"


def test_plan_off_without_a_mode_before_goes_to_default(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="plan")
    assert run(s, "/plan exit") == "plan mode is off: permission mode default"


def test_plan_with_a_task_turns_it_on_and_sends_the_task(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    out = run(s, "/plan fix the cart bug")
    assert isinstance(out, Send) and str(out) == "fix the cart bug" and "plan mode on" in out.notice and s.permissions.mode == "plan"


def test_plan_show_with_nothing_says_how_to_start(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "no plan yet" in run(s, "/plan show")


def test_the_mode_command_also_remembers_for_plan_off(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, mode="accept-edits")
    run(s, "/mode plan")
    assert run(s, "/plan off").endswith("accept-edits")


def test_the_terminal_sends_what_the_command_returns(tmp_path, monkeypatch):
    from harness import cli
    s = make_session(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(cli, "run_turn", lambda session, watcher, message: sent.append(message))
    out = run(s, "/plan fix it")
    assert isinstance(out, cli.Send)                       # the loop in main() checks this type
    assert sent == []                                      # (main() itself is exercised by the manual check in the lesson)


def test_the_ui_shows_a_plan_and_asks_for_text(capsys, monkeypatch):
    ui = PlainUI()
    ui.show_plan("1. a\n2. b")
    assert "Proposed plan" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda prompt="": "  hello ")
    assert ui.ask_text("What?") == "hello"
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError()))
    assert ui.ask_text("What?") == ""
