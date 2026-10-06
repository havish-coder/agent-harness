"""Lesson 20: settings layers, validation, and secrets kept out of settings files."""
import json
import subprocess

import pytest

from harness import config
from harness.config import ConfigError, load_dotenv, load_settings, parse_dotenv


@pytest.fixture
def home(tmp_path, monkeypatch):
    user = tmp_path / "home" / ".harness"
    monkeypatch.setattr(config, "USER_DIR", user)
    return user


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "project"
    (root / ".harness").mkdir(parents=True)
    return root


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


def test_layers_override_in_order(home, ws):
    write(home / "settings.json", {"model": "user-model", "max_steps": 30, "temperature": 0.2})
    write(ws / ".harness" / "settings.json", {"model": "project-model", "max_steps": 25})
    write(ws / ".harness" / "settings.local.json", {"max_steps": 15})
    env = {"HARNESS_TEMPERATURE": "0.7", "HARNESS_STREAM": "false"}
    settings, warnings = load_settings(ws, flags={"model": "flag-model", "think": None}, environ=env)
    assert (settings.model, settings.max_steps, settings.temperature, settings.stream) == ("flag-model", 15, 0.7, False)
    assert settings.sources["model"] == "flag" and settings.sources["max_steps"] == "local"
    assert settings.sources["temperature"] == "environment" and settings.sources["provider"] == "default"
    assert settings.think is False                       # a flag given as None doesn't override
    assert warnings == []


def test_unknown_keys_warn_with_a_suggestion(home, ws):
    write(ws / ".harness" / "settings.json", {"max_step": 3})
    _, warnings = load_settings(ws, environ={})
    assert warnings == ["project: unknown setting 'max_step' (did you mean 'max_steps'?)"]


@pytest.mark.parametrize("data,message", [
    ({"max_steps": "ten"}, "'max_steps' has the wrong type"),
    ({"stream": 1}, "'stream' has the wrong type"),
    ({"max_steps": True}, "'max_steps' has the wrong type"),
    ({"api_key": "x"}, "looks like a secret"),
    ({"model": "sk-ant-abcdefghijklmnopqrstuvwxyz"}, "looks like an API key"),
    ([1, 2], "must be a JSON object"),
])
def test_invalid_settings_are_errors(home, ws, data, message):
    write(ws / ".harness" / "settings.local.json", data)
    with pytest.raises(ConfigError, match=message):
        load_settings(ws, environ={})


def test_invalid_json_names_the_line(home, ws):
    write(ws / ".harness" / "settings.json", '{\n  "model": "x",\n}')
    with pytest.raises(ConfigError, match="invalid JSON at line 3"):
        load_settings(ws, environ={})


def test_bad_environment_value(home, ws):
    with pytest.raises(ConfigError, match="HARNESS_MAX_STEPS"):
        load_settings(ws, environ={"HARNESS_MAX_STEPS": "many"})


def test_project_settings_that_redirect_prompts_are_flagged(home, ws):
    write(ws / ".harness" / "settings.json", {"base_url": "http://203.0.113.9:8080/v1", "provider": "openai"})
    _, warnings = load_settings(ws, environ={})
    assert any("choose where your prompts are sent" in w and "203.0.113.9" in w for w in warnings)
    write(home / "settings.json", {"base_url": "http://localhost:1234/v1"})     # your own file: no warning
    (ws / ".harness" / "settings.json").unlink()
    assert load_settings(ws, environ={})[1] == []


def test_parse_dotenv():
    text = '# keys\nexport A=1\nB = "two words"\nC=\'x#y\'\nD=plain # comment\n\nbroken line\n'
    assert parse_dotenv(text) == {"A": "1", "B": "two words", "C": "x#y", "D": "plain"}


def test_load_dotenv_never_overrides_and_user_file_first(home, ws):
    write(home / ".env", "SHARED=user\nONLY_USER=1\n")
    write(ws / ".env", "SHARED=project\nONLY_PROJECT=2\nALREADY=project\n")
    env = {"ALREADY": "real"}
    loaded, _ = load_dotenv(ws, environ=env)
    assert env == {"ALREADY": "real", "SHARED": "user", "ONLY_USER": "1", "ONLY_PROJECT": "2"}
    assert set(loaded) == {"SHARED", "ONLY_USER", "ONLY_PROJECT"}


def test_dotenv_not_ignored_by_git_warns(home, ws):
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    write(ws / ".env", "K=v\n")
    _, warnings = load_dotenv(ws, environ={})
    assert warnings and "not ignored by git" in warnings[0]
    write(ws / ".gitignore", ".env\n")
    assert load_dotenv(ws, environ={})[1] == []
