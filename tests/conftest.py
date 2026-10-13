"""Shared test setup."""
import pytest

from harness import config


@pytest.fixture(autouse=True)
def no_hardware_probe(monkeypatch):
    """No test measures this machine's GPU or asks a model server how big a model is: a context window of "auto" is 8,192, as on a
    machine where nothing can be found out (Lesson 59). tests/test_hardware.py tests the probing itself, with faked answers."""
    monkeypatch.setattr("harness.context.windows.model_facts", lambda *a, **k: None)
    monkeypatch.setattr("harness.context.windows.usable_memory", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def isolated_user_folder(tmp_path_factory, monkeypatch):
    """No test may read or write the real ~/.harness (settings, trust, audit log). A test that wants a
    particular user folder sets config.USER_DIR itself, which overrides this."""
    monkeypatch.setattr(config, "USER_DIR", tmp_path_factory.mktemp("user-home") / ".harness")
