"""Domain model of the Lead & Qualification bounded context (M3, Sprint 2).

`Lead` mirrors the wacrm lead (wacrm is SoR for leads/pipeline, CON-2): the
aggregate never talks to wacrm itself — the Lead Sync Adapter is the single
read/write point (QA-08). `Lead.is_stale()` materializes QA-13: any business
decision on a lead older than the staleness bound must force a re-sync first.

`BuyerProfile` is the structured output of conversational qualification (E3):
`completeness()` implements the QA-14 gate input — five dimensions captured
progressively, one at a time (§6.2 progressive profiling).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from app.shared.domain.base import AggregateRoot, DomainEvent, Entity, ValueObject, new_id, utcnow


class PipelineStage(StrEnum):
    """wacrm pipeline stages (Architecture.md domain model). Values match the
    wacrm API verbatim — the Sync Adapter translates nothing here by design,
    so a stage wacrm doesn't know can never be pushed back to it."""

    NEW = "New"
    QUALIFIED = "Qualified"
    APPOINTMENT_SET = "AppointmentSet"
    VISITED = "Visited"
    NEGOTIATION = "Negotiation"
    WON = "Won"
    LOST = "Lost"


class Timeline(StrEnum):
    """When the buyer intends to purchase — one of the five profile dimensions."""

    IMMEDIATE = "immediate"
    THREE_MONTHS = "3_months"
    SIX_MONTHS = "6_months"
    OVER_SIX_MONTHS = "over_6_months"
    EXPLORING = "exploring"


class PropertyType(StrEnum):
    APARTMENT = "apartment"
    HOUSE = "house"
    LAND = "land"
    COMMERCIAL = "commercial"
    OTHER = "other"


class FinancingType(StrEnum):
    """How the buyer intends to pay — one of the seven profile dimensions
    (US-208)."""

    CASH = "cash"
    MORTGAGE_APPROVED = "mortgage_approved"
    MORTGAGE_PREAPPROVED = "mortgage_preapproved"
    EVALUATING = "evaluating"


class DecisionMakerMode(StrEnum):
    """Who is involved in the purchase decision — one of the seven profile
    dimensions (US-208)."""

    SOLO = "solo"
    COUPLE = "couple"
    FAMILY = "family"


#: The eight dimensions progressive profiling must fill (Architecture.md §6.2,
#: extended by US-208 with financing_type and decision_maker_mode, and by the
#: 2026-07-19 E2E review with bedrooms).
PROFILE_DIMENSIONS: tuple[str, ...] = (
    "budget",
    "locations",
    "property_type",
    "timeline",
    "must_haves",
    "financing_type",
    "decision_maker_mode",
    "bedrooms",
)


class ProfileValidationError(ValueError):
    """A ProfilePatch failed range/shape validation (e.g. budget <= 0). Raised
    before anything is persisted — invalid data never reaches the profile."""


@dataclass(frozen=True)
class MoneyRange(ValueObject):
    """Budget as a closed range. Currency handling is per-organization config;
    Sprint 2 stores the amounts as given by the conversation."""

    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        if self.minimum <= 0 or self.maximum <= 0:
            raise ProfileValidationError("Budget amounts must be positive")
        if self.minimum > self.maximum:
            raise ProfileValidationError("Budget minimum cannot exceed maximum")


@dataclass(frozen=True)
class ProfilePatch(ValueObject):
    """One progressive-profiling increment: only the dimensions the lead just
    answered. `None` means 'not part of this patch', never 'clear the value'."""

    budget: MoneyRange | None = None
    locations: tuple[str, ...] | None = None
    property_type: PropertyType | None = None
    timeline: Timeline | None = None
    must_haves: tuple[str, ...] | None = None
    financing_type: FinancingType | None = None
    decision_maker_mode: DecisionMakerMode | None = None
    bedrooms: int | None = None

    def __post_init__(self) -> None:
        if self.locations is not None and not self.locations:
            raise ProfileValidationError("locations patch cannot be an empty list")
        if self.must_haves is not None and not self.must_haves:
            raise ProfileValidationError("must_haves patch cannot be an empty list")
        if self.bedrooms is not None and not 1 <= self.bedrooms <= 15:
            raise ProfileValidationError("bedrooms must be between 1 and 15")

    def is_empty(self) -> bool:
        return all(
            getattr(self, dimension) is None for dimension in PROFILE_DIMENSIONS
        )


class BuyerProfile(Entity):
    """Structured output of conversational qualification (E3). Grows one
    dimension at a time; `completeness()` is the QA-14 gate input."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        lead_id: uuid.UUID,
        budget: MoneyRange | None = None,
        locations: tuple[str, ...] = (),
        property_type: PropertyType | None = None,
        timeline: Timeline | None = None,
        must_haves: tuple[str, ...] = (),
        financing_type: FinancingType | None = None,
        decision_maker_mode: DecisionMakerMode | None = None,
        bedrooms: int | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        self.id = id or new_id()
        self.lead_id = lead_id
        self.budget = budget
        self.locations = locations
        self.property_type = property_type
        self.timeline = timeline
        self.must_haves = must_haves
        self.financing_type = financing_type
        self.decision_maker_mode = decision_maker_mode
        self.bedrooms = bedrooms
        self.updated_at = updated_at or utcnow()

    def apply(self, patch: ProfilePatch) -> None:
        if patch.budget is not None:
            self.budget = patch.budget
        if patch.locations is not None:
            self.locations = tuple(patch.locations)
        if patch.property_type is not None:
            self.property_type = patch.property_type
        if patch.timeline is not None:
            self.timeline = patch.timeline
        if patch.must_haves is not None:
            self.must_haves = tuple(patch.must_haves)
        if patch.financing_type is not None:
            self.financing_type = patch.financing_type
        if patch.decision_maker_mode is not None:
            self.decision_maker_mode = patch.decision_maker_mode
        if patch.bedrooms is not None:
            self.bedrooms = patch.bedrooms
        self.updated_at = utcnow()

    def captured_dimensions(self) -> tuple[str, ...]:
        captured = []
        if self.budget is not None:
            captured.append("budget")
        if self.locations:
            captured.append("locations")
        if self.property_type is not None:
            captured.append("property_type")
        if self.timeline is not None:
            captured.append("timeline")
        if self.must_haves:
            captured.append("must_haves")
        if self.financing_type is not None:
            captured.append("financing_type")
        if self.decision_maker_mode is not None:
            captured.append("decision_maker_mode")
        if self.bedrooms is not None:
            captured.append("bedrooms")
        return tuple(captured)

    def missing_dimensions(self) -> tuple[str, ...]:
        captured = set(self.captured_dimensions())
        return tuple(d for d in PROFILE_DIMENSIONS if d not in captured)

    def completeness(self) -> float:
        """Percent of required dimensions captured, 0.0–100.0."""
        return 100.0 * len(self.captured_dimensions()) / len(PROFILE_DIMENSIONS)


class ObjectionType(StrEnum):
    """One of the five sales-objection categories the AI Agent tracks
    (US-209)."""

    PRECIO = "precio"
    ZONA = "zona"
    FINANCIAMIENTO = "financiamiento"
    TAMANO = "tamano"
    TIEMPO = "tiempo"


class LeadClassification(StrEnum):
    """Hot/Warm/Cold commercial-priority classification derived from
    `Lead.lead_score` (US-209)."""

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class FinancingReadiness(StrEnum):
    """3-state financing-readiness classification, orthogonal to the
    Hot/Warm/Cold `LeadClassification` (US-214). See design.md
    (lead-readiness-service-us-214) Decision 2 for the classification rule."""

    READY = "ready"
    PRE_READY = "pre_ready"
    DISCOVERY = "discovery"


class Objection(Entity):
    """One detected sales objection, append-only (a lead can raise the same
    `ObjectionType` more than once — each occurrence is its own row)."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        lead_id: uuid.UUID,
        organization_id: uuid.UUID,
        type: ObjectionType,
        raw_text: str,
        created_at: datetime | None = None,
    ) -> None:
        self.id = id or new_id()
        self.lead_id = lead_id
        self.organization_id = organization_id
        self.type = type
        self.raw_text = raw_text
        self.created_at = created_at or utcnow()


@dataclass(frozen=True)
class CRMStageSynced(DomainEvent):
    """A lead's pipeline stage was synced from wacrm (§7.7). Consumed by the
    Ownership Policy Engine and Staleness Guard in later iterations."""

    lead_id: str = ""
    crm_lead_id: str = ""
    pipeline_stage: str = ""
    synced_at: str = ""


@dataclass(frozen=True)
class ProfileCompleted(DomainEvent):
    """BuyerProfile crossed the completeness threshold (§7.8). The Lead Sync
    Adapter consumes it to push the qualified stage to wacrm via outbox."""

    lead_id: str = ""
    crm_lead_id: str = ""
    completeness: float = 0.0
    profile: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectionRecorded(DomainEvent):
    """An `Objection` was persisted and `Lead.lead_score`/`lead_classification`
    were recomputed (US-209). No consumer wired yet — future: notify the
    assigned broker on Hot->Cold transitions, or push classification to
    wacrm."""

    lead_id: str = ""
    crm_lead_id: str = ""
    objection_type: str = ""
    lead_score: float = 0.0
    lead_classification: str = ""


class Lead(AggregateRoot):
    """Local mirror of the wacrm lead. Only the Lead Sync Adapter writes it;
    every other module reads through `LeadSyncPort.get_lead` (QA-08)."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        organization_id: uuid.UUID,
        crm_lead_id: str,
        pipeline_stage: PipelineStage = PipelineStage.NEW,
        lead_score: float = 0.0,
        lead_classification: LeadClassification = LeadClassification.HOT,
        assigned_broker_id: uuid.UUID | None = None,
        contact_reference: str | None = None,
        synced_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self.id = id or new_id()
        self.organization_id = organization_id
        self.crm_lead_id = crm_lead_id
        self.pipeline_stage = pipeline_stage
        self.lead_score = lead_score
        self.lead_classification = lead_classification
        self.assigned_broker_id = assigned_broker_id
        self.contact_reference = contact_reference
        self.synced_at = synced_at or utcnow()
        self.created_at = created_at or utcnow()

    def is_stale(self, *, threshold_seconds: int, now: datetime | None = None) -> bool:
        """QA-13: True when the mirror exceeded the staleness bound and must be
        re-synced before any critical business decision."""
        reference = now or utcnow()
        return (reference - self.synced_at) > timedelta(seconds=threshold_seconds)

    def apply_objection_scoring(
        self, *, lead_score: float, lead_classification: LeadClassification
    ) -> None:
        """US-209: apply the locally-computed score/classification after an
        Objection is recorded. Separate from `mark_synced` since this writer
        is local, not a wacrm mirror update (see design.md Decision 3 and the
        Risks section on the two-writer conflict)."""
        self.lead_score = lead_score
        self.lead_classification = lead_classification

    def mark_synced(
        self,
        *,
        pipeline_stage: PipelineStage,
        lead_score: float,
        assigned_broker_id: uuid.UUID | None,
        contact_reference: str | None = None,
        synced_at: datetime | None = None,
    ) -> None:
        """Apply the wacrm snapshot. Idempotent: re-applying the same snapshot
        only refreshes `synced_at` (which is the point — QA-13 freshness)."""
        stage_changed = pipeline_stage is not self.pipeline_stage
        self.pipeline_stage = pipeline_stage
        self.lead_score = lead_score
        self.assigned_broker_id = assigned_broker_id
        if contact_reference is not None:
            self.contact_reference = contact_reference
        self.synced_at = synced_at or utcnow()
        if stage_changed:
            self.record_event(
                CRMStageSynced(
                    organization_id=self.organization_id,
                    lead_id=str(self.id),
                    crm_lead_id=self.crm_lead_id,
                    pipeline_stage=self.pipeline_stage.value,
                    synced_at=self.synced_at.isoformat(),
                )
            )
