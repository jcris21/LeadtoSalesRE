# tests/test_langsmith_tracing_config.py
"""Boot-time env wiring for LangSmith tracing — mirrors setup_observability's
role for OTel. Disabled by default: must not touch os.environ at all."""

import os

from app.core.config import Settings
from app.shared.infrastructure.observability import configure_langsmith_tracing


def _clear_langsmith_env(monkeypatch):
    for var in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)


def test_disabled_by_default_leaves_environment_untouched(monkeypatch):
    _clear_langsmith_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost/db",
        jwt_secret="test-secret",
    )

    configure_langsmith_tracing(settings)

    assert "LANGSMITH_TRACING" not in os.environ
    assert "LANGSMITH_API_KEY" not in os.environ


def test_enabled_sets_expected_environment_variables(monkeypatch):
    _clear_langsmith_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost/db",
        jwt_secret="test-secret",
        langsmith_tracing_enabled=True,
        langsmith_api_key="ls-test-key",
        langsmith_project="my-project",
        langsmith_endpoint="https://eu.api.smith.langchain.com",
    )

    configure_langsmith_tracing(settings)

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "ls-test-key"
    assert os.environ["LANGSMITH_PROJECT"] == "my-project"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://eu.api.smith.langchain.com"


def test_enabled_without_endpoint_does_not_set_it(monkeypatch):
    _clear_langsmith_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost/db",
        jwt_secret="test-secret",
        langsmith_tracing_enabled=True,
        langsmith_api_key="ls-test-key",
    )

    configure_langsmith_tracing(settings)

    assert "LANGSMITH_ENDPOINT" not in os.environ
