# tests/test_langsmith_config.py
"""LangSmith instrumentation config: off by default, same pattern as the
other optional-credential settings (gemini_api_key, otel_exporter_otlp_endpoint)."""

from app.core.config import Settings


def test_langsmith_settings_default_to_disabled_and_redacting(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    settings = Settings(_env_file=None)

    assert settings.langsmith_tracing_enabled is False
    assert settings.langsmith_api_key is None
    assert settings.langsmith_project == "lead-to-sales-system"
    assert settings.langsmith_endpoint is None
    assert settings.langsmith_redact_pii is True
