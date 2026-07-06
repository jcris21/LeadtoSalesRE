"""Guardrail Interceptor: broker-request detection BEFORE Coordinator reasoning
(QA-09, CRN-1; Architecture.md §7.5)."""

import pytest

from app.modules.conversation_ownership.application.guardrail import GuardrailInterceptor

guardrail = GuardrailInterceptor()


@pytest.mark.parametrize(
    ("message", "expected_name"),
    [
        ("¿Está María?", "María"),
        ("Hola, quiero hablar con María por favor", "María"),
        ("puedo hablar con la señora Lucía?", "Lucía"),
        ("Pásame con Carlos", "Carlos"),
        ("busco a Fernanda", "Fernanda"),
    ],
)
def test_detects_named_broker_request(message: str, expected_name: str):
    decision = guardrail.check(message)
    assert decision is not None
    assert decision.broker_requested == expected_name


@pytest.mark.parametrize(
    "message",
    [
        "quiero hablar con un asesor",
        "prefiero hablar con una persona real",
        "atiéndame un humano por favor",
    ],
)
def test_detects_generic_human_request(message: str):
    decision = guardrail.check(message)
    assert decision is not None
    assert decision.broker_requested is None


@pytest.mark.parametrize(
    "message",
    [
        "Hola, busco un departamento de 2 ambientes",
        "¿cuánto cuesta la propiedad del anuncio?",
        "me interesa la casa en Palermo",
        "¿está disponible la propiedad?",
        "quisiera agendar una visita",
    ],
)
def test_normal_lead_messages_do_not_bypass(message: str):
    assert guardrail.check(message) is None
