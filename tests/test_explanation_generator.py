"""Sprint 3A — Explanation Generator (Recommendation module M4).

Architecture.md §6.3 / §7.11: the Explanation Generator phrases the 2-3
already-selected winning `RankingSignal`s for one property in natural
language and must never invent a reason or reconsider the ranking. These
tests verify:

- the explanation text reflects the given signals (semantically, not by
  exact string match);
- an unrecognized signal name still yields a non-crashing, non-empty
  explanation (graceful fallback for signal names this module doesn't know);
- `explain()` is deterministic for the same inputs;
- zero signals doesn't crash and returns a sensible generic sentence;
- `ExplanationPort.explain`'s signature structurally has no full candidate
  list or score parameter — the "never hallucinate a reason" invariant is
  enforced by construction, not convention.
"""

from __future__ import annotations

import inspect
import uuid

from app.modules.recommendation.application.explanation_generator import (
    ExplanationGenerator,
    TemplatePhraser,
)
from app.modules.recommendation.domain.models import RankingSignal
from app.modules.recommendation.domain.ports import ExplanationPort


async def test_explanation_mentions_budget_signal():
    generator = ExplanationGenerator()
    property_id = uuid.uuid4()
    signals = (RankingSignal(name="budget_fit", weight=0.6, value=1.0),)

    explanation = await generator.explain(property_id=property_id, signals=signals)

    assert "presupuesto" in explanation


async def test_explanation_mentions_multiple_selected_signals():
    generator = ExplanationGenerator()
    property_id = uuid.uuid4()
    signals = (
        RankingSignal(name="budget_fit", weight=0.6, value=1.0),
        RankingSignal(name="zone_match", weight=0.3, value=1.0),
    )

    explanation = await generator.explain(property_id=property_id, signals=signals)

    assert "presupuesto" in explanation
    assert "zona" in explanation


async def test_unrecognized_signal_name_falls_back_gracefully():
    generator = ExplanationGenerator()
    property_id = uuid.uuid4()
    signals = (RankingSignal(name="school_proximity_score", weight=0.2, value=1.0),)

    explanation = await generator.explain(property_id=property_id, signals=signals)

    assert explanation  # non-empty
    assert "school proximity score" in explanation


async def test_explain_is_deterministic_for_same_signals():
    generator = ExplanationGenerator()
    property_id = uuid.uuid4()
    signals = (
        RankingSignal(name="budget_fit", weight=0.6, value=1.0),
        RankingSignal(name="zone_match", weight=0.3, value=1.0),
    )

    first = await generator.explain(property_id=property_id, signals=signals)
    second = await generator.explain(property_id=property_id, signals=signals)

    assert first == second


async def test_zero_signals_does_not_crash_and_returns_generic_sentence():
    generator = ExplanationGenerator()
    property_id = uuid.uuid4()

    explanation = await generator.explain(property_id=property_id, signals=())

    assert isinstance(explanation, str)
    assert explanation  # non-empty, sensible fallback


async def test_template_phraser_used_directly_is_also_deterministic():
    phraser = TemplatePhraser()
    property_id = uuid.uuid4()
    signals = (RankingSignal(name="must_have_coverage", weight=0.4, value=1.0),)

    explanation = await phraser.phrase(property_id=property_id, signals=signals)

    assert "requisitos indispensables" in explanation


def test_explanation_port_signature_has_no_candidate_list_or_score_param():
    """Structural guard for the anti-hallucination invariant (§7.11): the
    LLM/phraser must never receive the full candidate list or a score it
    could reinterpret — only `property_id` and the pre-selected `signals`."""
    signature = inspect.signature(ExplanationPort.explain)
    param_names = set(signature.parameters) - {"self"}

    assert param_names == {"property_id", "signals"}
    for forbidden in ("candidates", "properties", "property_list", "score", "scores"):
        assert forbidden not in param_names


def test_explanation_generator_explain_signature_matches_port():
    """Same guard applied to the concrete implementation, not just the
    Protocol: `ExplanationGenerator.explain` must not have grown extra
    parameters that would let a caller (accidentally) pass the full ranking
    context in."""
    signature = inspect.signature(ExplanationGenerator.explain)
    param_names = set(signature.parameters) - {"self"}

    assert param_names == {"property_id", "signals"}
