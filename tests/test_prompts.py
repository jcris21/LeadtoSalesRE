"""US-216: DEFAULT_SYSTEM_PROMPT content — non-form conversational tone,
2-consecutive-answers summary cadence, warm-professional register with
moderate emoji use. Pure content assertions: this prompt has no code path of
its own, it is sent verbatim by `CoordinatorAgent._load_system_prompt` as the
fallback whenever no per-organization prompt is published in the Prompt
Registry (see tests/test_prompt_registry.py for that wiring).
"""

from app.modules.conversation_ownership.domain.prompts import DEFAULT_SYSTEM_PROMPT


def test_prompt_instructs_non_form_natural_conversation():
    lowered = DEFAULT_SYSTEM_PROMPT.lower()
    assert "no formulario" in lowered
    assert "reconoce" in lowered or "eco" in lowered
    assert "varía" in lowered or "varia" in lowered


def test_prompt_instructs_summary_every_two_consecutive_answers():
    lowered = DEFAULT_SYSTEM_PROMPT.lower()
    assert "cada 2 respuestas" in lowered or "segunda respuesta consecutiva" in lowered
    assert "resumen" in lowered
    # The cadence must be explicitly tied to *before* the next question.
    assert "antes de" in lowered


def test_prompt_instructs_warm_professional_tone_with_moderate_emojis():
    lowered = DEFAULT_SYSTEM_PROMPT.lower()
    assert "cálido" in lowered or "calido" in lowered
    assert "profesional" in lowered
    assert "emoji" in lowered
    assert "moderación" in lowered or "moderacion" in lowered


def test_prompt_still_covers_all_four_stages():
    lowered = DEFAULT_SYSTEM_PROMPT.lower()
    for stage_keyword in ("saludo", "calificación", "recomendación", "derivación"):
        assert stage_keyword in lowered


def test_prompt_preserves_anti_hallucination_rules():
    lowered = DEFAULT_SYSTEM_PROMPT.lower()
    assert "no inventes" in lowered
    assert "no prometas precios" in lowered
    assert "contexto interno" in lowered


def test_prompt_preserves_prompt_injection_guard():
    lowered = DEFAULT_SYSTEM_PROMPT.lower()
    assert "nunca instrucciones para" in lowered
    assert "no pidas datos sensibles" in lowered


def test_prompt_invites_visit_conversationally_instead_of_promising_handoff():
    """US-221: US-212 (already merged) wired `run_scheduling_turn` to book a visit
    automatically the moment the lead's message carries a recognizable date+time — no
    human in the loop. The old step-4 language ("quiere agendar una visita -> asesor
    humano continuará") described a handoff that no longer happens for that case, so it
    must no longer be unconditional; the assistant should instead suggest a visit
    conversationally, tied to a property, and ask for a day/time preference."""
    lowered = DEFAULT_SYSTEM_PROMPT.lower()
    # The old unconditional phrase must be gone.
    assert "quiere agendar una visita o plantea algo fuera de tu alcance" not in lowered
    # New guidance: suggest a visit, connected to a property, asking for a day/time.
    assert "coordinar" in lowered or "coordinamos" in lowered
    assert "visita" in lowered
    assert "día" in lowered or "dia" in lowered or "horario" in lowered
    # Human handoff still exists, but narrowed to explicit/out-of-scope requests.
    assert "asesor humano" in lowered
    assert "hablar con una persona" in lowered


def test_prompt_bans_rigid_yes_no_scheduling_phrasing():
    lowered = DEFAULT_SYSTEM_PROMPT.lower()
    assert "sí/no" in lowered or "si/no" in lowered
    assert "desea agendar" in lowered
