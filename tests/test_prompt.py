"""Lesson 37: the system prompt as named sections, ordered for the prefix cache, within a budget."""
import datetime
import os
import shutil
import subprocess

import pytest

from harness import config
from harness.commands import load_commands
from harness.config import Settings
from harness.context.prompt import MIN_TRIM, PROMPT_SHARE, Section, assemble, environment_text, git_summary
from harness.context.tokens import estimate_tokens
from harness.session import ROLE, SYSTEM_PROMPT, WORKSPACE_HEADER, Session
from harness.tui.plain import PlainApprover, PlainUI
from harness.workspace import Workspace

# --- ordering -------------------------------------------------------------------------------

def test_sections_are_joined_most_stable_first():
    built = assemble([Section("files", "FILES", 2), Section("role", "ROLE", 0), Section("style", "STYLE", 1)])
    assert built.text == "ROLE\n\nSTYLE\n\nFILES"
    assert [p.name for p in built.parts] == ["role", "style", "files"]


def test_sections_of_equal_stability_keep_the_order_they_were_given():
    built = assemble([Section("b", "B", 1), Section("a", "A", 1), Section("c", "C", 1)])
    assert built.text == "B\n\nA\n\nC"


def test_empty_sections_leave_no_gap():
    built = assemble([Section("role", "ROLE", 0), Section("memory", "  \n", 1), Section("files", "FILES", 2)])
    assert built.text == "ROLE\n\nFILES" and [p.name for p in built.parts] == ["role", "files"]


def test_the_same_sections_give_the_same_bytes():
    def sections():
        return [Section("role", "ROLE", 0), Section("env", "Date: 2026-10-07", 2), Section("rule", "RULE", 1)]
    assert assemble(sections()).text == assemble(sections()).text


def test_a_change_late_in_the_prompt_leaves_the_start_alone():
    """The point of the order: a model server that remembers the start of the last prompt can reuse its work up to
    the first character that differs."""
    def prompt(date):
        return assemble([Section("role", "ROLE " * 50, 0), Section("rule", "RULE " * 20, 1),
                         Section("env", f"Date: {date}", 2)]).text
    one, two = prompt("2026-10-07"), prompt("2026-10-08")
    shared = os.path.commonprefix([one, two])
    assert one != two and shared.startswith("ROLE") and "RULE" in shared and len(shared) > len(one) - 20


def test_the_parts_report_what_each_costs():
    built = assemble([Section("role", "hello there", 0)])
    assert built.parts[0].tokens == estimate_tokens("hello there") and built.tokens == built.parts[0].tokens
    assert built.budget is None and not built.over_budget


# --- the budget -----------------------------------------------------------------------------

def listing(max_tokens: int) -> str:
    """A stand-in for the workspace listing: about one token per line, so the budget picks the line count."""
    return "files:\n" + "\n".join(f"f{i}" for i in range(max(1, max_tokens // 3)))


def test_nothing_changes_when_the_prompt_fits():
    sections = [Section("role", "ROLE", 0), Section("files", listing(30), 2, required=False, shrink=listing)]
    built = assemble(sections, budget=1_000)
    assert built.text == assemble(sections).text and all(not p.note for p in built.parts)


def test_a_listing_that_is_too_big_is_shrunk_first():
    big = Section("files", listing(900), 2, required=False, shrink=listing)
    built = assemble([Section("role", "ROLE " * 40, 0), big], budget=300)
    assert not built.over_budget and built.tokens <= 300
    files = next(p for p in built.parts if p.name == "files")
    assert files.note.startswith("shrunk from") and 0 < files.tokens < 300
    assert "ROLE" in built.text                                    # the role is untouched


def test_the_most_volatile_shrinkable_section_is_shrunk_before_a_steadier_one():
    steady = Section("steady", listing(500), 1, required=False, shrink=listing)
    volatile = Section("volatile", listing(500), 2, required=False, shrink=listing)
    built = assemble([steady, volatile], budget=700)
    notes = {p.name: p.note for p in built.parts}
    assert notes["volatile"].startswith("shrunk") and notes["steady"] == ""


def test_optional_sections_are_dropped_when_shrinking_is_not_enough():
    role = Section("role", "ROLE " * 100, 0)
    env = Section("environment", "Date: x\n" * 60, 2, required=False)
    style = Section("style", "Be brief. " * 60, 1, required=False)
    built = assemble([role, style, env], budget=estimate_tokens(role.text) + estimate_tokens(style.text) + 20)
    notes = {p.name: p.note for p in built.parts}
    assert notes["environment"].startswith("dropped") and notes["style"] == ""        # the most volatile goes first
    assert "Date:" not in built.text and "Be brief." in built.text
    assert built.tokens <= built.budget                                              # dropped parts do not count


def test_a_required_section_is_never_dropped_even_over_budget():
    built = assemble([Section("role", "ROLE " * 400, 0), Section("env", "x " * 50, 2, required=False)], budget=100)
    assert built.over_budget and "ROLE" in built.text and "x x" not in built.text
    assert [p.name for p in built.parts if "dropped" not in p.note] == ["role"]


def test_a_listing_never_shrinks_below_its_floor():
    """A listing of three tokens cannot shrink to nothing: it is dropped (it is optional) instead."""
    tiny = Section("files", listing(MIN_TRIM + 5), 2, required=False, shrink=listing)
    built = assemble([Section("role", "ROLE " * 100, 0), tiny], budget=estimate_tokens("ROLE " * 100) + 4)
    files = next(p for p in built.parts if p.name == "files")
    assert files.note.startswith(("dropped", "shrunk")) and built.tokens <= built.budget + MIN_TRIM


def test_an_approximate_shrink_is_asked_again_for_less():
    """A listing turns a token target into a line count, so its first answer can be no smaller than what it
    replaces. The assembly asks again for less rather than dropping the whole listing."""
    asked = []

    def rough(max_tokens):
        asked.append(max_tokens)
        return listing(max_tokens)
    built = assemble([Section("role", "ROLE " * 40, 0), Section("files", listing(900), 2, required=False, shrink=rough)],
                     budget=300)
    assert len(asked) > 1 and asked == sorted(asked, reverse=True)
    assert next(p for p in built.parts if p.name == "files").note.startswith("shrunk") and not built.over_budget


def test_a_section_that_cannot_get_smaller_stops_the_loop():
    stuck = Section("files", "x " * 300, 2, required=False, shrink=lambda tokens: "x " * 300)
    built = assemble([Section("role", "ROLE", 0), stuck], budget=50)
    assert next(p for p in built.parts if p.name == "files").note.startswith("dropped")


# --- the environment section ----------------------------------------------------------------

def test_the_environment_section_states_the_facts_the_model_cannot_know(tmp_path):
    text = environment_text(tmp_path, "PowerShell", datetime.date(2026, 10, 7), git=False)
    assert text.splitlines()[0] == "# Environment"
    assert "Date: 2026-10-07" in text and "Shell for run_shell: PowerShell" in text and "System: " in text
    assert "Git:" not in text


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@needs_git
def test_git_summary_names_the_branch_and_counts_changes(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "trunk"], cwd=tmp_path, check=True)
    assert git_summary(tmp_path) == "branch trunk, no changes"              # a repository with no commits has a branch too
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    assert git_summary(tmp_path) == "branch trunk, 2 changed files"
    (tmp_path / "b.txt").unlink()
    assert git_summary(tmp_path) == "branch trunk, 1 changed file"


@needs_git
def test_git_summary_is_none_outside_a_repository(tmp_path):
    assert git_summary(tmp_path / "nowhere") is None
    # a temporary folder is not inside a repository on any machine we run on; if one is, skip rather than fail
    if git_summary(tmp_path) is not None:
        pytest.skip("the temporary folder is inside a git work tree")


def test_git_summary_is_none_when_git_is_missing(tmp_path, monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(subprocess, "run", missing)
    assert git_summary(tmp_path) is None


# --- in the session -------------------------------------------------------------------------

class Quiet(PlainUI):
    def __call__(self, kind, data):
        pass

    def warn(self, text_):
        pass


def make_session(tmp_path, monkeypatch, **settings):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    (root / "notes.txt").write_text("hello", encoding="utf-8")
    return Session(Settings(**settings), Workspace(root), Quiet(), PlainApprover())


@pytest.fixture
def session(tmp_path, monkeypatch):
    return make_session(tmp_path, monkeypatch)


def test_the_session_builds_its_prompt_from_sections(session):
    names = [p.name for p in session.prompt.parts]
    assert names == ["role", "untrusted content", "clearing rule", "environment", "workspace files"]
    assert [p.stability for p in session.prompt.parts] == sorted(p.stability for p in session.prompt.parts)
    text = session.agent.messages[0].content
    assert text == session.prompt.text and text.startswith(ROLE)
    assert WORKSPACE_HEADER in text and "notes.txt" in text and "# Environment" in text


def test_the_prompt_budget_is_a_share_of_the_window(session):
    assert session.prompt.budget == int(8_192 * PROMPT_SHARE) and not session.prompt.over_budget


def test_the_untrusted_rule_is_left_out_when_fencing_is_off(tmp_path, monkeypatch):
    built = make_session(tmp_path, monkeypatch, fence_untrusted=False).prompt
    assert "untrusted content" not in [p.name for p in built.parts]


def test_a_style_goes_between_the_rules_and_the_session_facts(session):
    before = session.prompt.text
    session.set_style("pirate") if "pirate" in session.styles else session.set_style("concise")
    after = session.prompt.text
    names = [p.name for p in session.prompt.parts]
    assert names == ["role", "untrusted content", "clearing rule", "output style", "environment", "workspace files"]
    assert session.agent.messages[0].content == after == session.agent.system_prompt
    assert os.path.commonprefix([before, after]).startswith(ROLE)           # the role is shared, so it stays cached
    assert after.index("# Output style") < after.index("# Environment")
    session.set_style("default")
    assert session.prompt.text == before                                     # switching back gives the same bytes


def test_a_small_window_shrinks_the_listing_and_says_so(session):
    for i in range(200):
        (session.ws.root / f"module_{i:03}_with_a_long_descriptive_name.py").write_text("x", encoding="utf-8")
    session.context.window = 1_500                                           # a budget of 600 tokens
    built = session.build_prompt()
    files = next(p for p in built.parts if p.name == "workspace files")
    assert not built.over_budget and files.note.startswith("shrunk from")
    assert built.text.count("module_") < 200 and ROLE in built.text


def test_a_tiny_window_drops_what_is_optional_and_keeps_the_role(session):
    session.context.window = 300                                             # the budget never goes under 600
    built = session.build_prompt()
    assert built.budget == 600 and ROLE in built.text


def test_the_old_one_string_prompt_still_works_for_scripts():
    text = SYSTEM_PROMPT.format(snapshot="a.txt")
    assert text.startswith(ROLE) and text.endswith("a.txt") and WORKSPACE_HEADER in text


# --- /prompt --------------------------------------------------------------------------------

def run_prompt(session, args=""):
    return load_commands(session.ws.root).parse("/prompt " + args if args else "/prompt")[0].run(session, args)


def test_the_prompt_command_lists_the_sections(session):
    out = run_prompt(session)
    assert "system prompt: ~" in out and "2,048 budget" in out and "25% allowed" in out
    for name in ("role", "untrusted content", "environment", "workspace files"):
        assert name in out
    assert "never" in out and "per session" in out and "/prompt full" in out


def test_the_prompt_command_says_what_was_shrunk(session):
    for i in range(200):
        (session.ws.root / f"module_{i:03}_with_a_long_descriptive_name.py").write_text("x", encoding="utf-8")
    session.context.window = 1_500
    session.prompt = session.build_prompt()
    assert "[shrunk from" in run_prompt(session)


def test_prompt_full_prints_what_the_model_reads(session):
    assert run_prompt(session, "full") == session.agent.messages[0].content
