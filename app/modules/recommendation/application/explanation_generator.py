"""Explanation Generator (Sprint 3A, Recommendation module M4).

Architecture.md §6.3: "Redactar en lenguaje natural la explicación de un
ranking a partir de los signals reales que lo produjeron, nunca inventar una
razón." §7.11 spells out the sequence: the Ranking Engine selects the 2-3
highest-weight signals for one property (`RankedCandidate.top_signals()`)
*before* this module ever runs; this module only translates that already-
selected, already-decided tuple into a sentence.

The critical invariant (§7.11): "El LLM nunca recibe la lista completa de
propiedades ni decide el ranking — solo traduce signals ya calculados a
lenguaje natural (evita explicaciones alucinadas)." `ExplanationGenerator`
enforces this by construction: `explain()` accepts only `property_id` and
`signals` — there is no parameter through which a candidate list or a score
could leak in, so the phraser physically cannot reconsider the ranking.

Mirrors the pluggable-brain shape of
`app.modules.conversation_ownership.application.langgraph_responder`:
a `SignalPhraser` Protocol stands in for `ConversationBrain`, and
`TemplatePhraser` stands in for `TemplateBrain` — a deterministic default
that keeps the pipeline operational and testable without LLM credentials.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.recommendation.domain.models import RankingSignal

# Human-readable phrases for signal names the Ranking Engine is known to
# produce. Unknown names (the Ranking Engine workstream may add more) fall
# back to a generic snake_case -> readable-text conversion below, so this
# module never crashes or refuses to explain just because it doesn't
# recognize a name.
_SIGNAL_PHRASES: dict[str, str] = {
    "budget_fit": "ajustarse a tu presupuesto",
    "zone_match": "estar en la zona que buscás",
    "must_have_coverage": "cumplir con tus requisitos indispensables",
    "semantic_similarity": "coincidir con lo que describiste",
    "property_type_match": "ser del tipo de propiedad que buscás",
    # The Ranking Engine emits this name (ranking_engine.py) — without the
    # entry the raw "type match" leaked into the lead-facing message.
    "type_match": "ser del tipo de propiedad que buscás",
}


def _humanize(signal_name: str) -> str:
    """Readable Spanish-ish fragment for one signal name.

    Known names get a natural phrase from `_SIGNAL_PHRASES`; anything else
    (an unrecognized or future signal name) degrades gracefully to its
    snake_case words joined with spaces, so an unknown signal still yields
    a sensible, non-crashing explanation instead of being dropped or raising.
    """
    if signal_name in _SIGNAL_PHRASES:
        return _SIGNAL_PHRASES[signal_name]
    return signal_name.replace("_", " ").strip() or "un criterio relevante"


class SignalPhraser(Protocol):
    """Turns already-selected ranking signals for one property into a
    natural-language sentence. Equivalent seam to `ConversationBrain` in
    `langgraph_responder.py`: no ranking decisions happen here, only
    phrasing of facts handed in."""

    async def phrase(
        self, *, property_id: uuid.UUID, signals: tuple[RankingSignal, ...]
    ) -> str: ...


class TemplatePhraser:
    """Deterministic phraser: keeps the pipeline operational and testable
    without LLM credentials. An LLM-backed `SignalPhraser` implementation
    plugs in later behind this same Protocol — see the comment on
    `ExplanationGenerator.__init__` — without touching the rest of the
    Recommendation pipeline."""

    async def phrase(
        self, *, property_id: uuid.UUID, signals: tuple[RankingSignal, ...]
    ) -> str:
        del property_id  # not needed for phrasing; kept for Protocol symmetry
        if not signals:
            return "Esta propiedad forma parte de tus recomendaciones."

        fragments = [_humanize(signal.name) for signal in signals]
        if len(fragments) == 1:
            joined = fragments[0]
        else:
            joined = ", ".join(fragments[:-1]) + " y " + fragments[-1]

        return f"Esta propiedad destaca por {joined}."


class ExplanationGenerator:
    """`ExplanationPort` implementation. Deliberately accepts nothing beyond
    `property_id` and the already-selected `signals` tuple in `explain()` —
    there is no full candidate list or score parameter to accept, which is
    what makes the "never invent a reason" invariant (§6.3, §7.11) structural
    rather than a convention someone could forget."""

    def __init__(self, phraser: SignalPhraser | None = None) -> None:
        # An LLM-backed SignalPhraser plugs in here later; it would still
        # only ever see `property_id` + the selected `signals` tuple.
        self._phraser = phraser or TemplatePhraser()

    async def explain(
        self, *, property_id: uuid.UUID, signals: tuple[RankingSignal, ...]
    ) -> str:
        return await self._phraser.phrase(property_id=property_id, signals=signals)
