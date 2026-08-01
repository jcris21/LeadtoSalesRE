"""Characterization coverage for the recommendation narrator's LangSmith
instrumentation (Task 7). No test file existed for `llm_narrator.py` before
this task; this is deliberately narrow — one test locking `narrate()`'s
current behavior before decorating it, not a full new test suite for
pre-existing code (out of scope for this task)."""

import httpx
import pytest

from app.modules.recommendation.infrastructure.llm_narrator import (
    _SYSTEM_PROMPT,
    GeminiRecommendationNarrator,
)


def _narration_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]},
    )


@pytest.mark.asyncio
async def test_narrate_is_traceable_and_still_returns_text_when_tracing_disabled():
    """Characterization test: decorating narrate() with @traceable must not
    change its return value when tracing is disabled (default test env)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _narration_response("Este depa en Miraflores calza con tu presupuesto.")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    narrator = GeminiRecommendationNarrator("test-key", "gemini-2.5-flash", client)

    text = await narrator.narrate(
        profile={"name": "Ana Pérez", "email": "ana@example.com", "budget": "250000"},
        entries=[{"zone": "Miraflores", "property_type": "apartment"}],
    )

    assert text == "Este depa en Miraflores calza con tu presupuesto."


@pytest.mark.asyncio
async def test_narrate_returns_none_on_terminal_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    narrator = GeminiRecommendationNarrator("test-key", "gemini-2.5-flash", client)

    text = await narrator.narrate(profile={"name": "Ana"}, entries=[{"zone": "Miraflores"}])

    assert text is None


def test_system_prompt_closes_with_a_visit_tied_invitation_not_a_bare_preference_question():
    """US-221: the Top-3 paragraph's close must frame a visit as the natural next step
    tied to the recommended option, not just ask which option the lead prefers — while
    still never letting the LLM invent a date/time/availability (that stays
    `run_scheduling_turn`'s job downstream)."""
    lowered = _SYSTEM_PROMPT.lower()
    assert "visita" in lowered
    assert "coordinar" in lowered
    assert "no inventes datos" in lowered
    assert "cuál de las opciones prefiere o le gustaría visitar" not in lowered
