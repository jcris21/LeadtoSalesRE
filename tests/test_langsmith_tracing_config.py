# tests/test_langsmith_tracing_config.py
"""Boot-time env wiring for LangSmith tracing — mirrors setup_observability's
role for OTel. Disabled by default: must not touch os.environ at all."""

import os
from unittest.mock import patch

from app.core.config import Settings
from app.shared.infrastructure.observability import configure_langsmith_tracing
from app.shared.infrastructure.pii_redaction import redact_pii_deep


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

    with patch("app.shared.infrastructure.observability.get_cached_client") as mock_get_client:
        configure_langsmith_tracing(settings)
        mock_get_client.assert_not_called()

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

    with patch("app.shared.infrastructure.observability.get_cached_client"):
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

    with patch("app.shared.infrastructure.observability.get_cached_client"):
        configure_langsmith_tracing(settings)

    assert "LANGSMITH_ENDPOINT" not in os.environ


def test_enabled_with_redact_pii_seeds_client_with_deep_redaction_hooks(monkeypatch):
    """The fix for the whole-branch review's Critical finding: LangGraph's
    own auto-generated LangSmith runs bypass every per-call-site @traceable
    redaction hook. Seeding the shared client singleton's hide_inputs/
    hide_outputs with redact_pii_deep is the only hook that covers those."""
    _clear_langsmith_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost/db",
        jwt_secret="test-secret",
        langsmith_tracing_enabled=True,
        langsmith_api_key="ls-test-key",
        langsmith_redact_pii=True,
    )

    with patch("app.shared.infrastructure.observability.get_cached_client") as mock_get_client:
        configure_langsmith_tracing(settings)

    mock_get_client.assert_called_once_with(
        hide_inputs=redact_pii_deep, hide_outputs=redact_pii_deep
    )


def test_enabled_without_redact_pii_does_not_seed_client(monkeypatch):
    _clear_langsmith_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost/db",
        jwt_secret="test-secret",
        langsmith_tracing_enabled=True,
        langsmith_api_key="ls-test-key",
        langsmith_redact_pii=False,
    )

    with patch("app.shared.infrastructure.observability.get_cached_client") as mock_get_client:
        configure_langsmith_tracing(settings)
        mock_get_client.assert_not_called()
