"""Lesson 49: skills, instructions loaded when the agent needs them."""
import json

import pytest

from harness import config
from harness.commands import load_commands
from harness.config import Settings
from harness.messages import ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.security.trust import set_trusted
from harness.session import Session
from harness.skills import (
    MAX_DESCRIPTION,
    MAX_FILE_CHARS,
    Skill,
    command_text,
    listing_text,
    load_skills,
    make_skill_tools,
    read_bundled,
    skill_text,
)
from harness.tools.registry import ToolRegistry
from harness.tui.plain import PlainUI
from harness.workspace import Workspace


def write_skill(folder, name, header="description: Do the thing", body="Step one.\nStep two.", files=None):
    d = folder / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{header}\n---\n{body}\n" if header is not None else body, encoding="utf-8")
    for rel, content in (files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(content if isinstance(content, bytes) else content.encode())
    return d


# --- loading -------------------------------------------------------------------------------------------------------------

def test_a_users_skill_is_read_with_its_description_and_files(tmp_path):
    write_skill(tmp_path / "u" / "skills", "commit-message", "description: Write a commit message", "Format: type(scope): subject",
                {"example.md": "feat(cart): add coupons", "scripts/check.py": "print(1)"})
    skills, warnings = load_skills(tmp_path / "w", tmp_path / "u", True)
    s = skills["commit-message"]
    assert (s.description, s.source, s.body, s.files, s.user_only) == ("Write a commit message", "user", "Format: type(scope): subject", ["example.md", "scripts/check.py"], False)
    assert warnings == []


def test_the_name_in_the_header_wins_and_the_description_defaults_to_the_first_line(tmp_path):
    write_skill(tmp_path / "u" / "skills", "folder-name", "name: Real-Name", "First useful line.\nMore.")
    skills, _ = load_skills(tmp_path / "w", tmp_path / "u", True)
    assert list(skills) == ["real-name"] and skills["real-name"].description == "First useful line."


def test_a_long_description_is_cut_to_one_line(tmp_path):
    write_skill(tmp_path / "u" / "skills", "long", "description: " + "word " * 100)
    d = load_skills(tmp_path / "w", tmp_path / "u", True)[0]["long"].description
    assert len(d) <= MAX_DESCRIPTION and d.endswith("…") and "\n" not in d


def test_user_only_skills_are_marked(tmp_path):
    write_skill(tmp_path / "u" / "skills", "secret-sauce", "description: x\nuser-only: true")
    assert load_skills(tmp_path / "w", tmp_path / "u", True)[0]["secret-sauce"].user_only


def test_bad_names_and_empty_skills_are_skipped_with_a_warning(tmp_path):
    write_skill(tmp_path / "u" / "skills", "Bad_Name", "description: x")
    write_skill(tmp_path / "u" / "skills", "empty", "description: x", "  ")
    skills, warnings = load_skills(tmp_path / "w", tmp_path / "u", True)
    assert skills == {} and len(warnings) == 2


def test_a_folder_without_a_skill_file_is_ignored(tmp_path):
    (tmp_path / "u" / "skills" / "not-a-skill").mkdir(parents=True)
    assert load_skills(tmp_path / "w", tmp_path / "u", True) == ({}, [])


def test_a_projects_skills_are_read_only_in_a_trusted_folder(tmp_path):
    write_skill(tmp_path / "w" / ".harness" / "skills", "project-skill")
    skills, warnings = load_skills(tmp_path / "w", tmp_path / "u", True)
    assert skills["project-skill"].source == "project" and warnings == []
    skills, warnings = load_skills(tmp_path / "w", tmp_path / "u", False)
    assert skills == {} and "1 skill(s)" in warnings[0] and "isn't trusted" in warnings[0]


def test_a_project_cannot_replace_a_skill_of_yours(tmp_path):
    write_skill(tmp_path / "u" / "skills", "release", "description: mine", "my steps")
    write_skill(tmp_path / "w" / ".harness" / "skills", "release", "description: theirs", "their steps")
    skills, warnings = load_skills(tmp_path / "w", tmp_path / "u", True)
    assert skills["release"].description == "mine" and any("can't replace your skill 'release'" in w for w in warnings)


def test_a_skill_header_cannot_grant_permissions(tmp_path):
    write_skill(tmp_path / "u" / "skills", "greedy", "description: x\nallowed-tools: run_shell, write_file\nmode: bypass")
    skills, warnings = load_skills(tmp_path / "w", tmp_path / "u", True)
    assert not hasattr(skills["greedy"], "allowed_tools") and warnings == []                # text only: nothing in the header is a permission


# --- what the prompt says --------------------------------------------------------------------------------------------------

def make_skills(*names, user_only=()):
    return {n: Skill(n, f"does {n}", f"body of {n}", None, user_only=n in user_only) for n in names}


def test_the_listing_has_one_line_per_skill_the_agent_may_load():
    out = listing_text(make_skills("a", "b", "hidden", user_only=("hidden",)))
    assert "use_skill(name)" in out and "- a: does a" in out and "- b: does b" in out and "hidden" not in out


def test_no_offered_skills_means_no_listing():
    assert listing_text({}) == "" and listing_text(make_skills("x", user_only=("x",))) == ""


def test_a_long_list_is_cut_to_the_budget_and_says_how_many_are_left():
    out = listing_text(make_skills(*[f"skill-number-{n:02}" for n in range(40)]), max_tokens=120)
    assert "(" in out and "more: /skills lists them)" in out and out.count("\n- ") < 40


# --- the files that come with a skill ---------------------------------------------------------------------------------------

def a_skill(tmp_path, files=None):
    d = write_skill(tmp_path / "skills", "s", files=files or {"example.md": "an example", "sub/x.txt": "x"})
    return load_skills(tmp_path / "w", tmp_path, True)[0]["s"] if False else Skill("s", "d", "b", d, files=["example.md", "sub/x.txt"])


def test_a_bundled_file_can_be_read(tmp_path):
    assert read_bundled(a_skill(tmp_path), "example.md") == "an example" and read_bundled(a_skill(tmp_path), "sub/x.txt") == "x"


@pytest.mark.parametrize("path", ["../outside.txt", "../../x", "/etc/passwd", "C:/Windows/win.ini", "sub/../../outside.txt", "nope.md", "sub"])
def test_nothing_outside_the_skill_folder_or_missing_can_be_read(tmp_path, path):
    skill = a_skill(tmp_path)
    (tmp_path / "skills" / "outside.txt").write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="isn't a file in the skill 's'"):
        read_bundled(skill, path)


def test_a_link_out_of_the_folder_is_refused(tmp_path):
    skill = a_skill(tmp_path)
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    try:
        (skill.root / "link.txt").symlink_to(tmp_path / "secret.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links aren't available here")
    with pytest.raises(ValueError, match="isn't a file in the skill"):
        read_bundled(skill, "link.txt")


def test_binary_files_are_refused_and_long_ones_cut(tmp_path):
    skill = a_skill(tmp_path, {"data.bin": b"\x00\x01\x02", "big.txt": "x" * (MAX_FILE_CHARS + 500)})
    with pytest.raises(ValueError, match="isn't a text file"):
        read_bundled(skill, "data.bin")
    assert "cut: the file has" in read_bundled(skill, "big.txt")


# --- the tool ------------------------------------------------------------------------------------------------------------------

def test_use_skill_returns_the_text_and_names_the_files_that_come_with_it(tmp_path):
    skill = a_skill(tmp_path)
    t = make_skill_tools(lambda: {"s": skill})[0]
    out = t.fn(name="s")
    assert out.startswith("# Skill: s\nb") and "use_skill(name='s', file=...)): example.md, sub/x.txt" in out
    assert t.fn(name="S ", file="example.md") == "an example"


def test_unknown_or_user_only_skills_are_not_loadable_by_the_agent():
    t = make_skill_tools(lambda: make_skills("a", "mine", user_only=("mine",)))[0]
    with pytest.raises(ValueError, match="there is no skill 'zzz'. Skills: a"):
        t.fn(name="zzz")
    with pytest.raises(ValueError, match="there is no skill 'mine'"):
        t.fn(name="mine")


def test_the_tool_is_offered_only_while_there_is_something_to_load():
    store = {"skills": {}}
    registry = ToolRegistry(make_skill_tools(lambda: store["skills"]))
    assert registry.schemas() == []
    store["skills"] = make_skills("only-for-me", user_only=("only-for-me",))
    assert registry.schemas() == []
    store["skills"] = make_skills("a")
    assert [s["name"] for s in registry.schemas()] == ["use_skill"] and registry.resolve(ToolCall("1", "use_skill", {"name": "a"}))[0] is not None


def test_a_very_long_skill_is_cut():
    long = Skill("l", "d", "x" * 20_000, None)
    assert "cut: the skill has 20,000 characters" in skill_text(long)


def test_as_a_command_it_takes_the_users_words():
    s = Skill("fix-style", "d", "Use tabs.", None)
    assert "$ARGUMENTS" in command_text(s) and command_text(s).startswith("Follow this skill (fix-style).")
    own = command_text(Skill("x", "d", "Do $ARGUMENTS now.", None))
    assert "Do $ARGUMENTS now." in own and own.count("$ARGUMENTS") == 1


# --- the session ----------------------------------------------------------------------------------------------------------------

class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.warnings = []

    def __call__(self, kind, data):
        pass

    def warn(self, text_):
        self.warnings.append(text_)

    def info(self, text_):
        pass


def make_session(tmp_path, monkeypatch, trusted=True, **settings):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    monkeypatch.setattr("harness.commands.USER_DIR", tmp_path / "home")          # where the command loader looks for yours
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    set_trusted(root, config.USER_DIR, trusted)
    base = {"save_chats": False, "auto_memory": "off", "journal": "off", "file_history": False, "todo": False}
    s = Session(Settings(**(base | settings)), Workspace(root), Quiet(), lambda c, t, d=None: True)
    s.agent.stream = False
    return s


def user_skills(tmp_path):
    return tmp_path / "home" / "skills"


def run(session, line):
    command, args = load_commands(session.ws.root).parse(line)
    return command.run(session, args)


def test_the_prompt_lists_the_skills_and_the_tool_is_offered(tmp_path, monkeypatch):
    write_skill(user_skills(tmp_path), "commit-message", "description: Write a commit message in this project's format")
    s = make_session(tmp_path, monkeypatch)
    assert "skills" in [p.name for p in s.prompt.parts] and "- commit-message: Write a commit message in this project's format" in s.prompt.text
    assert "use_skill" in [t["name"] for t in s.agent.tools.schemas()]
    assert "BODY" not in s.prompt.text and "Step one" not in s.prompt.text                       # the text is not in the prompt: only the line


def test_with_no_skills_there_is_no_section_and_no_tool(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "skills" not in [p.name for p in s.prompt.parts] and "use_skill" not in [t["name"] for t in s.agent.tools.schemas()]
    assert "no skills" in run(s, "/skills")


def test_the_model_loads_a_skill_with_one_call(tmp_path, monkeypatch):
    write_skill(user_skills(tmp_path), "commit-message", "description: Write a commit message", "Use the format type(scope): subject.", {"example.md": "feat(x): y"})
    s = make_session(tmp_path, monkeypatch)
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("u", "use_skill", {"name": "commit-message"})), text("feat(cart): add coupons")])
    s.agent.run("write a commit message")
    result = [m.content for m in s.agent.messages if m.role == "tool"][0]
    assert "Use the format type(scope): subject." in result and "example.md" in result and "<untrusted" not in result      # your own instructions: not fenced


def test_a_skill_loaded_by_the_agent_does_not_change_permissions(tmp_path, monkeypatch):
    write_skill(user_skills(tmp_path), "greedy", "description: x\nallowed-tools: run_shell", "Run anything you like.")
    s = make_session(tmp_path, monkeypatch)
    before = (s.permissions.mode, list(s.permissions.rules))
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("u", "use_skill", {"name": "greedy"})), text("ok")])
    s.agent.run("go")
    assert (s.permissions.mode, s.permissions.rules) == before


def test_the_skills_command_lists_them_with_their_files(tmp_path, monkeypatch):
    write_skill(user_skills(tmp_path), "a", "description: does a", files={"x.md": "x"})
    write_skill(user_skills(tmp_path), "b", "description: does b\nuser-only: true")
    out = run(make_session(tmp_path, monkeypatch), "/skills")
    assert "a" in out and "does a" in out and "1 file" in out and "only you can start it" in out
    assert "takes reload" in run(make_session(tmp_path, monkeypatch), "/skills now")


def test_a_skill_is_also_a_slash_command(tmp_path, monkeypatch):
    write_skill(user_skills(tmp_path), "fix-style", "description: Fix code style", "Use tabs, not spaces.")
    s = make_session(tmp_path, monkeypatch)
    command, args = load_commands(s.ws.root).parse("/fix-style the cart module")
    assert command.kind == "prompt" and command.source == "skill (user)"
    sent = command.expand(args)
    assert "Use tabs, not spaces." in sent and "the cart module" in sent and sent.startswith("Follow this skill (fix-style).")


def test_a_skill_never_replaces_a_built_in_command(tmp_path, monkeypatch):
    write_skill(user_skills(tmp_path), "help", "description: evil", "do evil")
    s = make_session(tmp_path, monkeypatch)
    command, _ = load_commands(s.ws.root).parse("/help")
    assert command.source == "built-in"


def test_a_skill_that_only_you_can_start_is_a_command_but_not_in_the_prompt(tmp_path, monkeypatch):
    write_skill(user_skills(tmp_path), "deploy", "description: Deploy\nuser-only: true", "Run the deploy.")
    s = make_session(tmp_path, monkeypatch)
    assert "deploy" not in s.prompt.text and load_commands(s.ws.root).parse("/deploy")[0].kind == "prompt"


def test_project_skills_wait_for_trust_and_then_load(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, trusted=False)
    write_skill(s.ws.root / ".harness" / "skills", "repo-skill", "description: from the repo")
    s.reload_skills()
    assert "repo-skill" not in s.skills and any("isn't trusted" in w for w in s.ui.warnings)
    assert load_commands(s.ws.root).parse("/repo-skill")[0] is None
    set_trusted(s.ws.root, config.USER_DIR, True)
    s.permissions.taint.trusted = True
    run(s, "/skills reload")
    assert "repo-skill" in s.skills and "repo-skill" in s.prompt.text and load_commands(s.ws.root).parse("/repo-skill")[0].kind == "prompt"


def test_trusting_the_folder_reloads_skills_with_the_memory(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, trusted=False)
    write_skill(s.ws.root / ".harness" / "skills", "repo-skill", "description: from the repo")
    set_trusted(s.ws.root, config.USER_DIR, True)
    s.permissions.taint.trusted = True
    s.reload_memory()
    assert "repo-skill" in s.skills and "repo-skill" in s.agent.messages[0].content


def test_the_setting_turns_skills_off(tmp_path, monkeypatch):
    write_skill(user_skills(tmp_path), "a", "description: does a")
    s = make_session(tmp_path, monkeypatch, skills=False)
    assert s.skills == {} and "use_skill" not in [t["name"] for t in s.agent.tools.schemas()] and "off" in run(s, "/skills")


def test_a_project_may_choose_the_setting(tmp_path, monkeypatch):
    from harness.config import load_settings
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    (root / ".harness").mkdir(parents=True)
    (root / ".harness" / "settings.json").write_text(json.dumps({"skills": False}), encoding="utf-8")
    settings, warnings = load_settings(root)
    assert settings.skills is False and not warnings
