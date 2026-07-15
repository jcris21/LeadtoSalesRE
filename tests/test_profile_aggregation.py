"""US-211 — Profile Aggregation: synthesis of `conversation_memory` rows into
the `buyer_profiles.ai_profile` and `leads.buyer_persona` snapshots, strictly
independent of each other and of `PROFILE_DIMENSIONS`."""

import pytest
from sqlalchemy import select

from app.modules.conversation_memory.application.profile_aggregation import (
    ProfileAggregationService,
)
from app.modules.conversation_memory.domain.models import (
    ConversationMemoryObservation,
    MemoryType,
)
from app.modules.conversation_memory.infrastructure.repository import (
    ConversationMemoryRepository,
)
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.application.profile_capture import (
    BuyerProfileCaptureService,
)
from app.modules.lead_qualification.domain.models import Lead, MoneyRange, ProfilePatch
from app.modules.lead_qualification.infrastructure.db_models import BuyerProfileORM, LeadORM
from app.modules.lead_qualification.infrastructure.repository import LeadRepository
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded_lead_and_conversation(session_factory, org_id):
    async with session_factory() as session:
        session.add(
            OrganizationORM(id=org_id, name="Org Test", status="active", created_at=utcnow())
        )
        lead = Lead(organization_id=org_id, crm_lead_id="lead-1")
        await LeadRepository(session).add(lead)
        conversation = Conversation(
            organization_id=org_id, chatwoot_conversation_id="42", lead_id=lead.id
        )
        await ConversationRepository(session).add(conversation)
        await session.commit()
    return lead.id, conversation.id


async def _seed_observation(
    session_factory,
    *,
    conversation_id,
    lead_id,
    org_id,
    memory_type: MemoryType,
    value: dict,
    confidence: float = 0.6,
) -> None:
    async with session_factory() as session:
        await ConversationMemoryRepository(session).add(
            ConversationMemoryObservation(
                conversation_id=conversation_id,
                lead_id=lead_id,
                organization_id=org_id,
                memory_type=memory_type,
                entity_name="estilo_interior"
                if memory_type is MemoryType.STYLE_PREFERENCE
                else "contexto_familiar",
                value=value,
                confidence=confidence,
            )
        )
        await session.commit()


async def _seed_profile(session_factory, lead_id) -> None:
    async with session_factory() as session:
        await BuyerProfileCaptureService(session).update_profile(
            lead_id, ProfilePatch(budget=MoneyRange(50_000, 80_000))
        )
        await session.commit()


async def _read_snapshots(session_factory, lead_id) -> tuple[dict | None, dict | None]:
    async with session_factory() as session:
        lead_row = await session.get(LeadORM, lead_id)
        result = await session.execute(
            select(BuyerProfileORM).where(BuyerProfileORM.lead_id == lead_id)
        )
        profile_row = result.scalar_one_or_none()
        ai_profile = profile_row.ai_profile if profile_row is not None else None
        return ai_profile, lead_row.buyer_persona


# --- happy path -------------------------------------------------------------


async def test_aggregate_writes_both_snapshots(
    session_factory, seeded_lead_and_conversation, org_id
):
    lead_id, conversation_id = seeded_lead_and_conversation
    await _seed_profile(session_factory, lead_id)
    await _seed_observation(
        session_factory,
        conversation_id=conversation_id,
        lead_id=lead_id,
        org_id=org_id,
        memory_type=MemoryType.STYLE_PREFERENCE,
        value={"adjectives": ["minimalista", "luminoso"], "raw_text": "..."},
    )
    await _seed_observation(
        session_factory,
        conversation_id=conversation_id,
        lead_id=lead_id,
        org_id=org_id,
        memory_type=MemoryType.FAMILY_CONTEXT,
        value={"phrases": ["tenemos hijos", "tenemos mascota"], "raw_text": "..."},
    )

    async with session_factory() as session:
        result = await ProfileAggregationService(session).aggregate(
            lead_id=lead_id, organization_id=org_id
        )
        await session.commit()

    assert result.ai_profile is not None
    assert result.buyer_persona is not None

    ai_profile, buyer_persona = await _read_snapshots(session_factory, lead_id)
    assert ai_profile["modern_score"] == 1.0
    assert ai_profile["family_score"] == 1.0
    assert ai_profile["confidence"] == pytest.approx(0.6)
    assert ai_profile["observation_count"] == 2
    assert "computed_at" in ai_profile
    assert buyer_persona["family_stage"] == "family_with_children"
    assert buyer_persona["has_pets"] is True
    assert buyer_persona["communication"] == "whatsapp"
    assert "computed_at" in buyer_persona


# --- eligibility threshold ---------------------------------------------------


async def test_below_threshold_observations_are_excluded(
    session_factory, seeded_lead_and_conversation, org_id
):
    lead_id, conversation_id = seeded_lead_and_conversation
    await _seed_profile(session_factory, lead_id)
    await _seed_observation(
        session_factory,
        conversation_id=conversation_id,
        lead_id=lead_id,
        org_id=org_id,
        memory_type=MemoryType.STYLE_PREFERENCE,
        value={"adjectives": ["rustico"], "raw_text": "..."},
        confidence=0.3,
    )

    async with session_factory() as session:
        result = await ProfileAggregationService(session).aggregate(
            lead_id=lead_id, organization_id=org_id
        )
        await session.commit()

    assert result.ai_profile is None
    assert result.buyer_persona is None
    ai_profile, buyer_persona = await _read_snapshots(session_factory, lead_id)
    assert ai_profile is None
    assert buyer_persona is None


async def test_no_eligible_observations_leaves_existing_snapshots_untouched(
    session_factory, seeded_lead_and_conversation, org_id
):
    lead_id, conversation_id = seeded_lead_and_conversation
    await _seed_profile(session_factory, lead_id)
    await _seed_observation(
        session_factory,
        conversation_id=conversation_id,
        lead_id=lead_id,
        org_id=org_id,
        memory_type=MemoryType.STYLE_PREFERENCE,
        value={"adjectives": ["moderno"], "raw_text": "..."},
        confidence=0.9,
    )
    async with session_factory() as session:
        await ProfileAggregationService(session).aggregate(
            lead_id=lead_id, organization_id=org_id
        )
        await session.commit()
    ai_before, persona_before = await _read_snapshots(session_factory, lead_id)
    assert ai_before is not None

    # A later run where the only new signal is sub-threshold: the eligible set
    # is unchanged, so snapshots must stay as-is (recomputed to equal values).
    await _seed_observation(
        session_factory,
        conversation_id=conversation_id,
        lead_id=lead_id,
        org_id=org_id,
        memory_type=MemoryType.STYLE_PREFERENCE,
        value={"adjectives": ["rustico"], "raw_text": "..."},
        confidence=0.1,
    )
    async with session_factory() as session:
        await ProfileAggregationService(session).aggregate(
            lead_id=lead_id, organization_id=org_id
        )
        await session.commit()

    ai_after, persona_after = await _read_snapshots(session_factory, lead_id)
    assert {k: v for k, v in ai_after.items() if k != "computed_at"} == {
        k: v for k, v in ai_before.items() if k != "computed_at"
    }
    assert {k: v for k, v in persona_after.items() if k != "computed_at"} == {
        k: v for k, v in persona_before.items() if k != "computed_at"
    }


# --- idempotency -------------------------------------------------------------


async def test_aggregation_is_idempotent_over_unchanged_observations(
    session_factory, seeded_lead_and_conversation, org_id
):
    lead_id, conversation_id = seeded_lead_and_conversation
    await _seed_profile(session_factory, lead_id)
    await _seed_observation(
        session_factory,
        conversation_id=conversation_id,
        lead_id=lead_id,
        org_id=org_id,
        memory_type=MemoryType.STYLE_PREFERENCE,
        value={"adjectives": ["moderno", "rustico"], "raw_text": "..."},
    )

    async with session_factory() as session:
        first = await ProfileAggregationService(session).aggregate(
            lead_id=lead_id, organization_id=org_id
        )
        await session.commit()
    async with session_factory() as session:
        second = await ProfileAggregationService(session).aggregate(
            lead_id=lead_id, organization_id=org_id
        )
        await session.commit()

    def strip(snapshot: dict) -> dict:
        return {k: v for k, v in snapshot.items() if k != "computed_at"}

    assert strip(first.ai_profile) == strip(second.ai_profile)
    assert first.ai_profile["modern_score"] == 0.5


# --- snapshot independence ----------------------------------------------------


async def test_aggregation_never_mutates_qualification_dimensions(
    session_factory, seeded_lead_and_conversation, org_id
):
    lead_id, conversation_id = seeded_lead_and_conversation
    await _seed_profile(session_factory, lead_id)
    await _seed_observation(
        session_factory,
        conversation_id=conversation_id,
        lead_id=lead_id,
        org_id=org_id,
        memory_type=MemoryType.FAMILY_CONTEXT,
        value={"phrases": ["vivimos solos"], "raw_text": "..."},
    )

    async with session_factory() as session:
        result = await session.execute(
            select(BuyerProfileORM).where(BuyerProfileORM.lead_id == lead_id)
        )
        row = result.scalar_one()
        dims_before = (
            row.budget_min,
            row.budget_max,
            list(row.locations),
            row.property_type,
            row.timeline,
            list(row.must_haves),
            row.financing_type,
            row.decision_maker_mode,
        )

    async with session_factory() as session:
        await ProfileAggregationService(session).aggregate(
            lead_id=lead_id, organization_id=org_id
        )
        await session.commit()

    async with session_factory() as session:
        result = await session.execute(
            select(BuyerProfileORM).where(BuyerProfileORM.lead_id == lead_id)
        )
        row = result.scalar_one()
        dims_after = (
            row.budget_min,
            row.budget_max,
            list(row.locations),
            row.property_type,
            row.timeline,
            list(row.must_haves),
            row.financing_type,
            row.decision_maker_mode,
        )
        rows = await ConversationMemoryRepository(session).list_for_lead(lead_id)

    assert dims_after == dims_before
    assert len(rows) == 1  # append-only store untouched

    _, buyer_persona = await _read_snapshots(session_factory, lead_id)
    assert buyer_persona["family_stage"] == "couple_no_children"
    assert buyer_persona["has_pets"] is False


# --- graceful degradation ------------------------------------------------------


async def test_lead_without_buyer_profile_gets_only_persona(
    session_factory, seeded_lead_and_conversation, org_id
):
    lead_id, conversation_id = seeded_lead_and_conversation
    await _seed_observation(
        session_factory,
        conversation_id=conversation_id,
        lead_id=lead_id,
        org_id=org_id,
        memory_type=MemoryType.FAMILY_CONTEXT,
        value={"phrases": ["tenemos hijos"], "raw_text": "..."},
    )

    async with session_factory() as session:
        result = await ProfileAggregationService(session).aggregate(
            lead_id=lead_id, organization_id=org_id
        )
        await session.commit()

    assert result.ai_profile is None
    assert result.buyer_persona is not None

    async with session_factory() as session:
        profile_row = (
            await session.execute(
                select(BuyerProfileORM).where(BuyerProfileORM.lead_id == lead_id)
            )
        ).scalar_one_or_none()
        lead_row = await session.get(LeadORM, lead_id)
    assert profile_row is None  # no BuyerProfile created as a side effect
    assert lead_row.buyer_persona["family_stage"] == "family_with_children"


# --- tenant isolation -----------------------------------------------------------


async def test_cross_tenant_aggregation_is_rejected(
    session_factory, seeded_lead_and_conversation, org_id
):
    lead_id, conversation_id = seeded_lead_and_conversation
    await _seed_observation(
        session_factory,
        conversation_id=conversation_id,
        lead_id=lead_id,
        org_id=org_id,
        memory_type=MemoryType.STYLE_PREFERENCE,
        value={"adjectives": ["moderno"], "raw_text": "..."},
    )
    other_org_id = new_id()

    async with session_factory() as session:
        with pytest.raises(LeadNotFoundError):
            await ProfileAggregationService(session).aggregate(
                lead_id=lead_id, organization_id=other_org_id
            )

    ai_profile, buyer_persona = await _read_snapshots(session_factory, lead_id)
    assert ai_profile is None
    assert buyer_persona is None
