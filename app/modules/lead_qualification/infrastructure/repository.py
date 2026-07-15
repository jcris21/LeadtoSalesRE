"""Repositories translating between the M3 domain objects and their ORM rows."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    DecisionMakerMode,
    FinancingType,
    Lead,
    LeadClassification,
    MoneyRange,
    Objection,
    ObjectionType,
    PipelineStage,
    PropertyType,
    Timeline,
)
from app.modules.lead_qualification.infrastructure.db_models import (
    BuyerProfileORM,
    CRMAccessAuditORM,
    LeadObjectionORM,
    LeadORM,
    SyncCursorORM,
)
from app.shared.domain.base import new_id, utcnow

#: Watermark for organizations that never synced: epoch, so the first CDC poll
#: picks up every existing lead.
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _ensure_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class LeadRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, lead: Lead) -> None:
        self._session.add(self._to_row(lead))

    async def get(self, lead_id: uuid.UUID) -> Lead | None:
        row = await self._session.get(LeadORM, lead_id)
        return self._to_domain(row) if row is not None else None

    async def get_by_crm_id(self, organization_id: uuid.UUID, crm_lead_id: str) -> Lead | None:
        result = await self._session.execute(
            select(LeadORM).where(
                LeadORM.organization_id == organization_id,
                LeadORM.crm_lead_id == crm_lead_id,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def get_by_contact_reference(
        self, organization_id: uuid.UUID, contact_reference: str
    ) -> Lead | None:
        """Local-mirror lookup for Conversation<->Lead identity matching
        (Sprint 3): tried before falling back to a live wacrm call, since the
        CDC poll usually already mirrored the lead locally."""
        result = await self._session.execute(
            select(LeadORM).where(
                LeadORM.organization_id == organization_id,
                LeadORM.contact_reference == contact_reference,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def save(self, lead: Lead) -> None:
        row = await self._session.get(LeadORM, lead.id)
        if row is None:
            await self.add(lead)
            return
        row.pipeline_stage = lead.pipeline_stage.value
        row.lead_score = lead.lead_score
        row.lead_classification = lead.lead_classification.value
        row.assigned_broker_id = lead.assigned_broker_id
        row.contact_reference = lead.contact_reference
        row.synced_at = lead.synced_at

    @staticmethod
    def _to_row(lead: Lead) -> LeadORM:
        return LeadORM(
            id=lead.id,
            organization_id=lead.organization_id,
            crm_lead_id=lead.crm_lead_id,
            pipeline_stage=lead.pipeline_stage.value,
            lead_score=lead.lead_score,
            lead_classification=lead.lead_classification.value,
            assigned_broker_id=lead.assigned_broker_id,
            contact_reference=lead.contact_reference,
            synced_at=lead.synced_at,
            created_at=lead.created_at,
        )

    @staticmethod
    def _to_domain(row: LeadORM) -> Lead:
        # SQLite (tests) returns naive datetimes even for timezone=True columns;
        # values are stored as UTC, so re-attach UTC on hydration.
        return Lead(
            id=row.id,
            organization_id=row.organization_id,
            crm_lead_id=row.crm_lead_id,
            pipeline_stage=PipelineStage(row.pipeline_stage),
            lead_score=row.lead_score,
            lead_classification=LeadClassification(row.lead_classification),
            assigned_broker_id=row.assigned_broker_id,
            contact_reference=row.contact_reference,
            synced_at=_ensure_utc(row.synced_at),
            created_at=_ensure_utc(row.created_at),
        )


class BuyerProfileRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_lead_id(self, lead_id: uuid.UUID) -> BuyerProfile | None:
        result = await self._session.execute(
            select(BuyerProfileORM).where(BuyerProfileORM.lead_id == lead_id)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def save(self, organization_id: uuid.UUID, profile: BuyerProfile) -> None:
        row = await self._session.get(BuyerProfileORM, profile.id)
        if row is None:
            row = BuyerProfileORM(
                id=profile.id, organization_id=organization_id, lead_id=profile.lead_id
            )
            self._session.add(row)
        row.budget_min = profile.budget.minimum if profile.budget else None
        row.budget_max = profile.budget.maximum if profile.budget else None
        row.locations = list(profile.locations)
        row.property_type = profile.property_type.value if profile.property_type else None
        row.timeline = profile.timeline.value if profile.timeline else None
        row.must_haves = list(profile.must_haves)
        row.financing_type = profile.financing_type.value if profile.financing_type else None
        row.decision_maker_mode = (
            profile.decision_maker_mode.value if profile.decision_maker_mode else None
        )
        row.updated_at = profile.updated_at

    @staticmethod
    def _to_domain(row: BuyerProfileORM) -> BuyerProfile:
        budget = None
        if row.budget_min is not None and row.budget_max is not None:
            budget = MoneyRange(minimum=row.budget_min, maximum=row.budget_max)
        return BuyerProfile(
            id=row.id,
            lead_id=row.lead_id,
            budget=budget,
            locations=tuple(row.locations or ()),
            property_type=PropertyType(row.property_type) if row.property_type else None,
            timeline=Timeline(row.timeline) if row.timeline else None,
            must_haves=tuple(row.must_haves or ()),
            financing_type=FinancingType(row.financing_type) if row.financing_type else None,
            decision_maker_mode=(
                DecisionMakerMode(row.decision_maker_mode) if row.decision_maker_mode else None
            ),
            updated_at=row.updated_at,
        )


class LeadObjectionRepository:
    """Append-only sales-objection log persistence (US-209)."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, objection: Objection) -> None:
        self._session.add(
            LeadObjectionORM(
                id=objection.id,
                organization_id=objection.organization_id,
                lead_id=objection.lead_id,
                type=objection.type.value,
                raw_text=objection.raw_text,
                created_at=objection.created_at,
            )
        )

    async def list_for_lead(self, lead_id: uuid.UUID) -> list[Objection]:
        result = await self._session.execute(
            select(LeadObjectionORM)
            .where(LeadObjectionORM.lead_id == lead_id)
            .order_by(LeadObjectionORM.created_at)
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def count_for_lead(self, lead_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(LeadObjectionORM).where(
                LeadObjectionORM.lead_id == lead_id
            )
        )
        return int(result.scalar_one())

    async def count_distinct_types_for_lead(self, lead_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count(func.distinct(LeadObjectionORM.type))).where(
                LeadObjectionORM.lead_id == lead_id
            )
        )
        return int(result.scalar_one())

    @staticmethod
    def _to_domain(row: LeadObjectionORM) -> Objection:
        return Objection(
            id=row.id,
            lead_id=row.lead_id,
            organization_id=row.organization_id,
            type=ObjectionType(row.type),
            raw_text=row.raw_text,
            created_at=_ensure_utc(row.created_at),
        )


class SyncCursorRepository:
    """SyncCursorPort: makes CDC polling resumable after any crash (§7.7)."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_watermark(self, organization_id: uuid.UUID) -> datetime:
        row = await self._session.get(SyncCursorORM, organization_id)
        if row is None:
            return EPOCH
        watermark = row.watermark
        return watermark if watermark.tzinfo else watermark.replace(tzinfo=UTC)

    async def advance_watermark(self, organization_id: uuid.UUID, new_watermark: datetime) -> None:
        """Monotonic: never moves backwards, so a re-run cannot reopen a window."""
        row = await self._session.get(SyncCursorORM, organization_id)
        if row is None:
            self._session.add(
                SyncCursorORM(
                    organization_id=organization_id,
                    watermark=new_watermark,
                    updated_at=utcnow(),
                )
            )
            return
        current = row.watermark if row.watermark.tzinfo else row.watermark.replace(tzinfo=UTC)
        if new_watermark > current:
            row.watermark = new_watermark
            row.updated_at = utcnow()


class CRMAccessAuditRepository:
    """QA-08 audit log writer — one row per CRM access, allowed or denied."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        actor: str,
        action: str,
        crm_lead_id: str | None,
        allowed: bool,
        detail: dict | None = None,
    ) -> None:
        self._session.add(
            CRMAccessAuditORM(
                id=new_id(),
                organization_id=organization_id,
                actor=actor,
                action=action,
                crm_lead_id=crm_lead_id,
                allowed=allowed,
                detail=detail or {},
                occurred_at=utcnow(),
            )
        )

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[CRMAccessAuditORM]:
        result = await self._session.execute(
            select(CRMAccessAuditORM)
            .where(CRMAccessAuditORM.organization_id == organization_id)
            .order_by(CRMAccessAuditORM.occurred_at)
        )
        return list(result.scalars().all())
