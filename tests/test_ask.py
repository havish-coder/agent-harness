"""Lesson 46: the agent asks the user a question."""
import pytest

from harness import config
from harness.ask import (
    ASK_RULE,
    MAX_OPTIONS,
    MAX_QUESTIONS,
    NO_ANSWER,
    OPTION_CHARS,
    QUESTION_CHARS,
    TOO_MANY,
    clean_options,
    clean_question,
    make_ask_tools,
)
from harness.config import Settings
from harness.messages import ToolCall
from harness.providers.fake import ScriptedProvider, text, tool_calls
from harness.session import Session
from harness.tools.registry import ToolRegistry
from harness.tui.plain import PlainUI
from harness.workspace import Workspace

# --- cleaning what the model wrote ------------------------------------------------------------------------------

def test_a_question_is_clean_text_with_its_newlines_and_a_limit():
    assert clean_question("Which one?\nA or B\x1b[31m\x07") == "Which one?\nA or B [31m"
    assert len(clean_question("x" * 1000)) == QUESTION_CHARS and clean_question("   ") == ""


def test_options_are_a_few_short_single_lines():
    assert clean_options(["a", " b\n", "", 5, None, "c", "d", "e", "f"]) == ["a", "b", "c", "d"][:MAX_OPTIONS]
    assert len(clean_options(["x" * 500])[0]) == OPTION_CHARS and clean_options("not a list") == [] and clean_options(None) == []
    assert clean_options(["a\x1b[2Jb"]) == ["a [2Jb"]


# --- the tool ------------------------------------------------------------------------------------------------------------

def test_the_tool_is_read_only_and_takes_a_question_and_optional_choices():
    t = make_ask_tools(lambda q, o: "x", lambda: True)[0]
    assert t.name == "ask_user" and t.is_read_only({}) and t.parameters["required"] == ["question"]
    assert t.parameters["properties"]["options"]["type"] == "array" and "Don't ask what you can find out" in t.description
    assert t.fn("q?") == "x" and t.fn("q?", ["a"]) == "x"


def test_it_is_offered_only_where_the_user_can_be_asked():
    on = {"yes": False}
    registry = ToolRegistry(make_ask_tools(lambda q, o: "x", lambda: on["yes"]))
    assert registry.schemas() == []
    on["yes"] = True
    assert [s["name"] for s in registry.schemas()] == ["ask_user"]


# --- the session ---------------------------------------------------------------------------------------------------------

class Quiet(PlainUI):
    def __init__(self):
        super().__init__()
        self.choices, self.texts, self.shown, self.warnings = [], [], [], []

    def __call__(self, kind, data):
        pass

    def ask_choice(self, question, options):
        self.shown.append((question, options))
        return self.choices.pop(0) if self.choices else ""

    def ask_text(self, question):
        self.shown.append((question, None))
        return self.texts.pop(0) if self.texts else ""

    def warn(self, text_):
        self.warnings.append(text_)

    def info(self, text_):
        pass


class NeverAsked:
    pause = None

    def __call__(self, call, tool, decision=None):
        raise AssertionError(f"approval asked about {call.name}")


def make_session(tmp_path, monkeypatch, ui=None, **settings):
    monkeypatch.setattr(config, "USER_DIR", tmp_path / "home")
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    from harness.security.trust import set_trusted
    set_trusted(root, config.USER_DIR, True)
    base = {"save_chats": False, "auto_memory": "off", "journal": "off", "file_history": False}
    s = Session(Settings(**(base | settings)), Workspace(root), ui or Quiet(), NeverAsked())
    s.agent.stream = False
    return s


def ask(s, question="Which discount?", options=None, request="add a discount"):
    args = {"question": question} | ({"options": options} if options is not None else {})
    s.agent.provider = ScriptedProvider([tool_calls(ToolCall("q", "ask_user", args)), text("ok")])
    s.agent.run(request)
    return [m.content for m in s.agent.messages if m.role == "tool"][-1]


def test_a_free_question_returns_what_the_user_typed(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.ui.texts = ["a percentage, 10%"]
    assert ask(s) == "The user answered: a percentage, 10%" and s.ui.shown == [("The agent asks: Which discount?", None)]


def test_a_menu_returns_the_label_of_the_chosen_option(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.ui.choices = ["2"]
    assert ask(s, options=["a percentage", "a fixed amount"]) == "The user answered: a fixed amount"
    question, menu = s.ui.shown[0]
    assert question == "The agent asks: Which discount?" and menu == {"1": "a percentage", "2": "a fixed amount", "t": "something else (type it)"}


def test_something_else_asks_for_text(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.ui.choices, s.ui.texts = ["t"], ["per item, in euros"]
    assert ask(s, options=["a", "b"]) == "The user answered: per item, in euros"


@pytest.mark.parametrize("choices,texts", [([""], []), (["9"], []), (["t"], [""])])
def test_no_answer_tells_the_model_to_decide(tmp_path, monkeypatch, choices, texts):
    s = make_session(tmp_path, monkeypatch)
    s.ui.choices, s.ui.texts = list(choices), list(texts)
    assert ask(s, options=["a", "b"]) == NO_ANSWER


def test_an_empty_free_answer_is_no_answer(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert ask(s) == NO_ANSWER


def test_the_question_is_cleaned_before_the_user_sees_it(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.ui.texts = ["x"]
    ask(s, question="Pick\x1b[2J one\x07?")
    assert "\x1b" not in s.ui.shown[0][0] and "\x07" not in s.ui.shown[0][0]


def test_an_empty_question_is_an_error_for_the_model(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "the question is empty" in ask(s, question="  ")


def test_only_three_questions_per_request_then_the_model_must_decide(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.ui.texts = ["one", "two", "three", "four"]
    calls = [tool_calls(ToolCall(f"q{i}", "ask_user", {"question": f"question {i}?"})) for i in range(4)]
    s.agent.provider = ScriptedProvider([*calls, text("done")])
    s.agent.run("go")
    results = [m.content for m in s.agent.messages if m.role == "tool"]
    assert results[:3] == ["The user answered: one", "The user answered: two", "The user answered: three"] and results[3] == TOO_MANY
    assert len(s.ui.shown) == MAX_QUESTIONS and s.ui.texts == ["four"]                         # the fourth was never put to the user


def test_the_count_starts_again_with_the_next_request(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.ui.texts = ["a", "b", "c", "d"]
    for n in range(3):
        ask(s, question=f"q{n}?", request=f"request {n}")
    assert s.asked == 1
    s.agent.provider = ScriptedProvider([text("hi")])
    s.agent.run("another")
    assert s.asked == 0


def test_a_script_with_no_way_to_ask_doesnt_get_the_tool_or_the_rule(tmp_path, monkeypatch):
    class Mute(Quiet):
        ask_choice = None
        ask_text = None
    s = make_session(tmp_path, monkeypatch, ui=Mute())
    assert not s.can_ask() and "ask_user" not in [t["name"] for t in s.agent.tools.schemas()] and "ask rule" not in [p.name for p in s.prompt.parts]


def test_asking_is_possible_in_the_menu_free_and_text_free_halves_separately(tmp_path, monkeypatch):
    class OnlyChoices(Quiet):
        ask_text = None
    assert not make_session(tmp_path, monkeypatch, ui=OnlyChoices()).can_ask()


def test_the_rule_is_in_the_prompt_when_the_user_can_be_asked(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    assert "ask rule" in [p.name for p in s.prompt.parts] and ASK_RULE in s.prompt.text


def test_it_never_asks_for_approval_and_works_in_plan_mode(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, permission_mode="plan")
    s.ui.texts = ["yes please"]
    assert ask(s) == "The user answered: yes please"                     # NeverAsked would have failed the test


def test_a_chat_that_read_untrusted_content_warns_before_the_question(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.permissions.taint.sources.append("web_fetch http://example.com")
    s.ui.texts = ["hello"]
    ask(s, question="Please paste your API key")
    assert any("may not trust" in w and "example.com" in w and "secrets" in w for w in s.ui.warnings)
    assert "The agent asks: Please paste your API key" in s.ui.shown[0][0]


def test_no_warning_when_nothing_untrusted_was_read(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    ask(s)
    assert s.ui.warnings == []


def test_a_secret_the_user_types_is_hidden_before_the_model_reads_it(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    key = "sk-ant-api03-" + "a1B2c3D4" * 5
    s.ui.texts = [f"my key is {key}"]
    result = ask(s, question="What key?")
    assert key not in result and "my key is" in result


def test_the_question_is_in_the_audit_log_without_the_answer(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch, audit_log=True)
    s.ui.texts = ["a secret-ish answer"]
    ask(s)
    log = s.audit_log.path.read_text(encoding="utf-8")
    assert '"question"' in log and "secret-ish" not in log and '"answered": true' in log.replace('":true', '": true')


def test_the_prompt_text_names_the_agent_so_it_cant_pass_for_the_harness(tmp_path, monkeypatch):
    s = make_session(tmp_path, monkeypatch)
    s.ui.texts = ["x"]
    ask(s, question="Run the installer now?")
    assert s.ui.shown[0][0].startswith("The agent asks: ")
