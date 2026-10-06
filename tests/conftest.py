"""Shared test setup."""
import pytest

from harness import config


@pytest.fixture(autouse=True)
def isolated_user_folder(tmp_path_factory, monkeypatch):
    """No test may read or write the real ~/.harness (settings, trust, audit log). A test that wants a
    particular user folder sets config.USER_DIR itself, which overrides this."""
    monkeypatch.setattr(config, "USER_DIR", tmp_path_factory.mktemp("user-home") / ".harness")
