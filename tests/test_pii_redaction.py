# tests/test_pii_redaction.py
"""Pure-function PII scrubber for anything sent to the external LangSmith
SaaS: lead conversations carry real emails and phone numbers."""

from app.shared.infrastructure.pii_redaction import redact_pii, redact_pii_deep


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


def test_redact_pii_deep_walks_nested_langgraph_shaped_state():
    """Reproduces the shape of a real LangGraph `TurnState` payload
    (messages list of dicts, user_input, summary) — the run-tree data
    LangGraph's own auto-instrumentation submits to LangSmith, which no
    per-call-site @traceable hook covers."""
    state = {
        "user_input": "hola soy Ana, mi correo es ana@example.com, tel 987654321",
        "summary": "",
        "messages": [
            {"role": "user", "content": "hola, llamame al +51 987 654 321"},
            {"role": "assistant", "content": "¡Claro! Cuéntame más."},
        ],
        "bedrooms": 3,
    }

    redacted = redact_pii_deep(state)

    assert "ana@example.com" not in redacted["user_input"]
    assert "987654321" not in redacted["user_input"]
    assert "[REDACTED_EMAIL]" in redacted["user_input"]
    assert "[REDACTED_PHONE]" in redacted["user_input"]
    assert "+51 987 654 321" not in redacted["messages"][0]["content"]
    assert redacted["messages"][1]["content"] == "¡Claro! Cuéntame más."  # no PII, unchanged
    assert redacted["bedrooms"] == 3  # non-string values pass through untouched


def test_redact_pii_deep_handles_tuples_and_non_string_leaves():
    assert redact_pii_deep(("hola ana@example.com", 5, None)) == ("hola [REDACTED_EMAIL]", 5, None)
    assert redact_pii_deep(42) == 42
    assert redact_pii_deep(None) is None
