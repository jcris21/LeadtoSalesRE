"""Recommendation Service — the M4 facade (`RecommendationPort`, §6.1.1, §7.10).

Orchestrates the five independently-built Sprint 3 pieces end to end:
Structured Filter -> Semantic Retrieval -> Ranking Engine -> Explanation
Generator -> Neighborhood Enrichment. Nothing here re-implements pipeline
logic; this class only threads data between the ports and shapes the result.

QA-14 precondition: Sprint 3 depends on Sprint 2's completeness gate the same
way the Staleness Guard gates critical CRM decisions — `search()` refuses to
run the (expensive) pipeline against a profile that isn't ready yet, mirroring
`Documents/Oficial/ImplementationPlan.md` Sprint 3's stated dependency
("Sprint 2: perfil completo como precondición de búsqueda").

QA-13 precondition: `search()` is itself a critical business decision over
`Lead` data (§7.9), so it runs through the Staleness Guard first — mirroring
Architecture.md's sequence diagram (Coordinator -> Guard -> force re-sync if
stale -> proceed with fresh data). This is the missing wiring the Staleness
Guard needed: the guard's own logic was already correct, it just had no
caller on any real decision path.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

from app.core.config import get_settings
from app.modules.lead_qualification.application.completeness_gate import CompletenessGate
from app.modules.lead_qualification.domain.models import BuyerProfile
from app.modules.recommendation.domain.models import RecommendationItem, RecommendationResult
from app.modules.recommendation.domain.ports import (
    ExplanationPort,
    NeighborhoodEnrichmentPort,
    RankingEnginePort,
    SemanticRetrievalPort,
    StructuredFilterPort,
)


class IncompleteProfileError(ValueError):
    """Raised when `search()` is called for a lead with no BuyerProfile yet,
    or one that hasn't crossed the QA-14 completeness threshold."""


class BuyerProfileLookup(Protocol):
    """The one BuyerProfile read this facade needs. Satisfied structurally by
    `app.modules.lead_qualification.infrastructure.repository.BuyerProfileRepository`
    — no import of that class here, so this module stays testable without a DB."""

    async def get_by_lead_id(self, lead_id: uuid.UUID) -> BuyerProfile | None: ...


class StalenessCheck(Protocol):
    """The one Staleness Guard call this facade needs (§7.9, QA-13). Satisfied
    structurally by `app.modules.lead_qualification.application.staleness_guard
    .StalenessGuard` — no import of that class (or of `AsyncSession`) here, so
    this module stays testable without a DB."""

    async def check_before_decision(self, lead_id: uuid.UUID) -> object: ...


class RecommendationStore(Protocol):
    """US-310 audit persistence. Satisfied structurally by
    `infrastructure.repository.RecommendationRepository`; optional so facade
    unit tests need no DB. Persisting here (not in wiring) keeps the audit
    trail complete for every future caller (Coordinator, Handoff Builder)."""

    async def save_result(
        self,
        *,
        organization_id: uuid.UUID,
        buyer_profile_id: uuid.UUID | None,
        result: RecommendationResult,
    ) -> None: ...


class RecommendationService:
    """`RecommendationPort` implementation."""

    def __init__(
        self,
        *,
        buyer_profiles: BuyerProfileLookup,
        structured_filter: StructuredFilterPort,
        semantic_retrieval: SemanticRetrievalPort,
        ranking_engine: RankingEnginePort,
        explanation: ExplanationPort,
        neighborhood_enrichment: NeighborhoodEnrichmentPort,
        completeness_gate: CompletenessGate | None = None,
        staleness_guard: StalenessCheck | None = None,
        recommendation_store: RecommendationStore | None = None,
        semantic_top_n: int | None = None,
        top_k: int | None = None,
        enrichment_timeout_ms: int | None = None,
    ) -> None:
        settings = get_settings()
        self._buyer_profiles = buyer_profiles
        self._structured_filter = structured_filter
        self._semantic_retrieval = semantic_retrieval
        self._ranking_engine = ranking_engine
        self._explanation = explanation
        self._neighborhood_enrichment = neighborhood_enrichment
        self._completeness_gate = completeness_gate or CompletenessGate()
        self._staleness_guard = staleness_guard
        self._recommendation_store = recommendation_store
        self._semantic_top_n = semantic_top_n or settings.recommendation_semantic_top_n
        self._top_k = top_k or settings.recommendation_top_k
        self._enrichment_timeout_ms = (
            enrichment_timeout_ms or settings.recommendation_enrichment_timeout_ms
        )

    async def search(
        self, *, organization_id: uuid.UUID, lead_id: uuid.UUID
    ) -> RecommendationResult:
        if self._staleness_guard is not None:
            # §7.9: forces a synchronous re-sync when the Lead mirror exceeded
            # the staleness bound, then proceeds with fresh data. No
            # warn-and-continue fallback — a `LeadNotFoundError` here is
            # allowed to propagate and abort the search rather than run a
            # critical decision on data that may be stale or gone.
            await self._staleness_guard.check_before_decision(lead_id)

        buyer_profile = await self._buyer_profiles.get_by_lead_id(lead_id)
        if buyer_profile is None:
            raise IncompleteProfileError(f"No BuyerProfile found for lead {lead_id}")

        gate_result = self._completeness_gate.can_advance_to_recommendation(buyer_profile)
        if not gate_result.can_advance:
            raise IncompleteProfileError(
                f"BuyerProfile for lead {lead_id} is only "
                f"{gate_result.completeness:.0f}% complete "
                f"(missing: {gate_result.missing_dimension})"
            )

        candidates = await self._structured_filter.filter_candidates(
            organization_id=organization_id, buyer_profile=buyer_profile
        )
        # No short-circuit on an empty `candidates`: Semantic Retrieval and
        # Ranking Engine both already handle an empty input by returning an
        # empty result (see their own test suites), so letting them run keeps
        # this method's control flow uniform regardless of filter outcome.
        retrieved = await self._semantic_retrieval.retrieve(
            buyer_profile=buyer_profile, candidates=candidates, top_n=self._semantic_top_n
        )
        ranked = self._ranking_engine.rank(
            buyer_profile=buyer_profile, candidates=retrieved, top_k=self._top_k
        )
        if not ranked:
            return RecommendationResult(lead_id=lead_id, items=())

        explanations = await asyncio.gather(
            *(
                self._explanation.explain(
                    property_id=candidate.property_id, signals=candidate.top_signals()
                )
                for candidate in ranked
            )
        )
        insights = await self._neighborhood_enrichment.enrich_top3(
            lead_id=lead_id,
            property_ids=[candidate.property_id for candidate in ranked],
            timeout_ms=self._enrichment_timeout_ms,
        )

        items = tuple(
            RecommendationItem(
                property_id=candidate.property_id,
                rank=rank,
                score=candidate.score,
                explanation=explanation_text,
                neighborhood=insights.get(candidate.property_id),
                signals=candidate.signals,
            )
            for rank, (candidate, explanation_text) in enumerate(
                zip(ranked, explanations, strict=True), start=1
            )
        )
        result = RecommendationResult(lead_id=lead_id, items=items)
        if self._recommendation_store is not None:
            # US-310: audit trail — one row per ranked item, before returning,
            # so every caller (wiring today, Coordinator later) is covered.
            await self._recommendation_store.save_result(
                organization_id=organization_id,
                buyer_profile_id=buyer_profile.id,
                result=result,
            )
        return result
