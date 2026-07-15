"""US-209 — Objection detection + Hot/Warm/Cold classification: one
happy-path extraction per `ObjectionType`, the scoring/classification
formula, tenant isolation, and the ObjectionRecorded event."""

import pytest
from sqlalchemy import select

from app.modules.lead_qualification.application.lead_scoring import (
    classify,
    compute_lead_score,
)
from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.application.qualification_flow import extract_objection
from app.modules.lead_qualification.domain.models import Lead, LeadClassification, ObjectionType
from app.modules.lead_qualification.infrastructure.repository import (
    LeadObjectionRepository,
    LeadRepository,
)
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded_lead(session_factory, org_id):
    async with session_factory() as session:
        session.add(
            OrganizationORM(id=org_id, name="Org Test", status="active", created_at=utcnow())
        )
        lead = Lead(organization_id=org_id, crm_lead_id="lead-1")
        await LeadRepository(session).add(lead)
        await session.commit()
    return lead.id


# --- scoring formula -----------------------------------------------------


def test_compute_lead_score_no_objections_is_full_score():
    assert compute_lead_score(distinct_objection_types=0, total_objection_count=0) == 100.0


def test_compute_lead_score_one_objection():
    assert compute_lead_score(distinct_objection_types=1, total_objection_count=1) == 80.0


def test_compute_lead_score_floors_at_zero():
    assert compute_lead_score(distinct_objection_types=5, total_objection_count=20) == 0.0


def test_classify_boundaries():
    assert classify(100.0) is LeadClassification.HOT
    assert classify(70.0) is LeadClassification.HOT
    assert classify(69.9) is LeadClassification.WARM
    assert classify(40.0) is LeadClassification.WARM
    assert classify(39.9) is LeadClassification.COLD
    assert classify(0.0) is LeadClassification.COLD


def test_new_lead_defaults_to_hot():
    lead = Lead(organization_id=new_id(), crm_lead_id="lead-x")
    assert lead.lead_classification is LeadClassification.HOT


# --- extraction: one happy path per ObjectionType -------------------------


@pytest.mark.parametrize(
    "text,expected_type",
    [
        ("Uy, está muy caro para mi presupuesto", ObjectionType.PRECIO),
        ("No me gusta la zona, queda muy lejos", ObjectionType.ZONA),
        ("El banco me dice que no califico para el crédito", ObjectionType.FINANCIAMIENTO),
        ("Es muy pequeño, necesito más espacio", ObjectionType.TAMANO),
        ("Aún no es el momento para mí", ObjectionType.TIEMPO),
    ],
)
async def test_extract_objection_happy_path(
    session_factory, seeded_lead, org_id, text, expected_type
):
    async with session_factory() as session:
        result = await extract_objection(
            session, lead_id=seeded_lead, organization_id=org_id, text=text
        )
        await session.commit()
    assert result is expected_type

    async with session_factory() as session:
        objections = await LeadObjectionRepository(session).list_for_lead(seeded_lead)
    assert len(objections) == 1
    assert objections[0].type is expected_type
    assert objections[0].raw_text == text


async def test_extract_objection_no_signal(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_objection(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Me encanta, cuando podemos visitar",
        )
    assert result is None


async def test_cross_tenant_objection_extraction_is_rejected(session_factory, seeded_lead):
    other_org_id = new_id()
    async with session_factory() as session:
        with pytest.raises(LeadNotFoundError):
            await extract_objection(
                session,
                lead_id=seeded_lead,
                organization_id=other_org_id,
                text="Está muy caro",
            )


# --- score/classification recompute + ObjectionRecorded -------------------


async def test_recording_objection_updates_lead_score_and_classification(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        await extract_objection(
            session, lead_id=seeded_lead, organization_id=org_id, text="Está muy caro"
        )
        await session.commit()

    async with session_factory() as session:
        lead = await LeadRepository(session).get(seeded_lead)
    assert lead.lead_score == 80.0
    assert lead.lead_classification is LeadClassification.HOT


async def test_repeated_objections_keep_eroding_score(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        await extract_objection(
            session, lead_id=seeded_lead, organization_id=org_id, text="Está muy caro"
        )
        await extract_objection(
            session, lead_id=seeded_lead, organization_id=org_id, text="No me gusta la zona"
        )
        await extract_objection(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="El banco me dice que no califico",
        )
        await session.commit()

    async with session_factory() as session:
        lead = await LeadRepository(session).get(seeded_lead)
    # 3 distinct types, 3 total: 100 - 15*3 - 5*3 = 40.0
    assert lead.lead_score == 40.0
    assert lead.lead_classification is LeadClassification.WARM


async def test_objection_recorded_event_published(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        await extract_objection(
            session, lead_id=seeded_lead, organization_id=org_id, text="Está muy caro"
        )
        await session.commit()

    async with session_factory() as session:
        events = (
            (
                await session.execute(
                    select(OutboxEventORM).where(OutboxEventORM.event_type == "ObjectionRecorded")
                )
            )
            .scalars()
            .all()
        )
    assert len(events) == 1
    assert events[0].payload["fields"]["objection_type"] == "precio"
    assert events[0].payload["fields"]["lead_score"] == 80.0
    assert events[0].payload["fields"]["lead_classification"] == "hot"
