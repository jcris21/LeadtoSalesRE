"""Ranking Engine (M4, Sprint 3A) — Architecture.md §6.3, §7.10.

`WeightedRankingEngine` is the sole deterministic-scoring seam of the
Recommendation pipeline: it takes the candidates Structured Filter and
Semantic Retrieval already narrowed down, and combines a small set of
human-legible `RankingSignal`s into `score = Σ(signal.weight × value)`.

Sync, not async: this is pure in-memory arithmetic over data already loaded
by the caller (no DB round-trip, no LLM call, no network I/O) — matching
`RankingEnginePort.rank` in `domain/ports.py`, which is declared as a plain
(non-async) method for that reason.

Signal names are part of the contract with the Explanation Generator
(§7.11): each name must read as a short, natural-language-ready phrase
("budget_fit", not "bf_score"), because the Explanation Generator only ever
receives `RankedCandidate.signals` / `.top_signals()` — never the raw
candidate list — and must phrase *only* what the signals actually say.
"""

from __future__ import annotations

from app.modules.lead_qualification.domain.models import BuyerProfile
from app.modules.recommendation.domain.models import (
    Property,
    RankedCandidate,
    RankingSignal,
)


class WeightedRankingEngine:
    """Deterministic, LLM-free scorer implementing `RankingEnginePort`.

    Weights are class constants (not config) on purpose: the score formula
    is a documented, auditable business rule (§7.10), not a tunable model —
    any change to a weight is a code review, not a runtime config edit.
    """

    #: Budget fit rewards properties centered in the buyer's range; price is
    #: usually the buyer's hardest constraint, so it carries the most weight.
    BUDGET_FIT_WEIGHT = 0.4

    #: Zone match is a strong, binary buyer preference signal (location is
    #: rarely negotiable once stated), so it is weighted second-highest.
    ZONE_MATCH_WEIGHT = 0.3

    #: Must-have coverage rewards properties that satisfy more of the
    #: buyer's stated must-have features; partial credit is intentional
    #: since buyers rarely get every must-have in one property.
    MUST_HAVE_COVERAGE_WEIGHT = 0.2

    #: Type match is a smaller tie-breaker signal: property_type is usually
    #: already enforced upstream by Structured Filter as a hard constraint,
    #: so here it only nudges ranking when it slips through as a soft input.
    TYPE_MATCH_WEIGHT = 0.1

    def rank(
        self, *, buyer_profile: BuyerProfile, candidates: list[Property], top_k: int = 3
    ) -> list[RankedCandidate]:
        """Score every candidate, sort by score descending, return top_k.

        Ties are broken by candidate order in the input `candidates` list
        (Python's `sorted` is stable), so callers that want a specific
        tie-break (e.g. by recency or by property id) should pre-sort
        `candidates` accordingly before calling `rank`.
        """
        ranked = [
            self._score_candidate(buyer_profile=buyer_profile, candidate=candidate)
            for candidate in candidates
        ]
        ranked.sort(key=lambda candidate: candidate.score, reverse=True)
        return ranked[:top_k]

    def _score_candidate(
        self, *, buyer_profile: BuyerProfile, candidate: Property
    ) -> RankedCandidate:
        signals = (
            RankingSignal(
                name="budget_fit",
                weight=self.BUDGET_FIT_WEIGHT,
                value=self._budget_fit(buyer_profile=buyer_profile, candidate=candidate),
            ),
            RankingSignal(
                name="zone_match",
                weight=self.ZONE_MATCH_WEIGHT,
                value=self._zone_match(buyer_profile=buyer_profile, candidate=candidate),
            ),
            RankingSignal(
                name="must_have_coverage",
                weight=self.MUST_HAVE_COVERAGE_WEIGHT,
                value=self._must_have_coverage(buyer_profile=buyer_profile, candidate=candidate),
            ),
            RankingSignal(
                name="type_match",
                weight=self.TYPE_MATCH_WEIGHT,
                value=self._type_match(buyer_profile=buyer_profile, candidate=candidate),
            ),
        )
        score = sum(signal.contribution for signal in signals)
        return RankedCandidate(property_id=candidate.id, score=score, signals=signals)

    @staticmethod
    def _budget_fit(*, buyer_profile: BuyerProfile, candidate: Property) -> float:
        """1.0 when the price sits exactly at the budget midpoint, decaying
        linearly to 0.0 at either edge, and 0.0 outside the range entirely.

        Structured Filter should already exclude out-of-range candidates
        (§6.3), but this signal degrades gracefully instead of assuming
        that invariant holds, so a stray out-of-range candidate never
        raises — it just scores worst on this signal.
        """
        budget = buyer_profile.budget
        if budget is None:
            return 0.0
        if budget.minimum > budget.maximum:
            return 0.0
        if not (budget.minimum <= candidate.price <= budget.maximum):
            return 0.0

        span = budget.maximum - budget.minimum
        if span == 0:
            # Degenerate zero-width range: price already equals both edges.
            return 1.0

        midpoint = (budget.minimum + budget.maximum) / 2
        distance_from_midpoint = abs(candidate.price - midpoint)
        half_span = span / 2
        return max(0.0, 1.0 - (distance_from_midpoint / half_span))

    @staticmethod
    def _zone_match(*, buyer_profile: BuyerProfile, candidate: Property) -> float:
        """1.0 if the candidate's zone is one of the buyer's requested
        locations, else 0.0. Binary on purpose: a location is a stated
        preference, not a spectrum, and partial "nearby zone" credit would
        require geo data this signal deliberately does not depend on."""
        if not buyer_profile.locations:
            return 0.0
        return 1.0 if candidate.zone in buyer_profile.locations else 0.0

    @staticmethod
    def _must_have_coverage(*, buyer_profile: BuyerProfile, candidate: Property) -> float:
        """Fraction of the buyer's must_haves present in the candidate's
        features. A buyer with no stated must-haves contributes 0.0 rather
        than a vacuous 1.0 — an empty requirement set carries no signal."""
        if not buyer_profile.must_haves:
            return 0.0
        matched = sum(1 for feature in buyer_profile.must_haves if feature in candidate.features)
        return matched / len(buyer_profile.must_haves)

    @staticmethod
    def _type_match(*, buyer_profile: BuyerProfile, candidate: Property) -> float:
        """1.0 if the candidate's property_type matches the buyer's stated
        preference, else 0.0. Absent a stated preference, this contributes
        0.0 (no opinion, not a free match)."""
        if buyer_profile.property_type is None:
            return 0.0
        return 1.0 if candidate.property_type is buyer_profile.property_type else 0.0
