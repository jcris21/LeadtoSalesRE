# tests/test_pii_redaction.py
"""Pure-function PII scrubber for anything sent to the external LangSmith
SaaS: lead conversations carry real emails and phone numbers."""

from app.shared.infrastructure.pii_redaction import redact_pii


def test_redacts_email_addresses():
    text = "Contáctame a maria.lopez@example.com por favor"
    result = redact_pii(text)
    assert "maria.lopez@example.com" not in result
    assert "[REDACTED_EMAIL]" in result


def test_redacts_peru_and_generic_phone_numbers():
    assert "[REDACTED_PHONE]" in redact_pii("Mi número es +51 987 654 321")
    assert "[REDACTED_PHONE]" in redact_pii("Llámame al 987654321")
    assert "[REDACTED_PHONE]" in redact_pii("tel: (01) 555-1234")


def test_leaves_non_pii_text_untouched():
    text = "Busco un departamento de 3 dormitorios en Miraflores, presupuesto 250000 soles"
    assert redact_pii(text) == text


def test_handles_none_and_empty_gracefully():
    assert redact_pii("") == ""
    assert redact_pii(None) is None
