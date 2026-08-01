"""US-212: the scheduling turn is the missing caller that turns a lead's
in-chat slot confirmation into a `SchedulingService.book_visit` call. Covers
`extract_confirmed_slot`'s deterministic recognition contract and
`run_scheduling_turn`'s resolution + delegation, using the same seeding
patterns as tests/test_scheduling_service.py (broker/availability) and
tests/test_coordinator_qualification_turn.py (conversation/lead)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.appointment.domain.models import (
    AvailabilityCheck,
    AvailabilityCheckSource,
    AvailabilityStatus,
    Broker,
    CalendarEventResult,
)
from app.modules.appointment.infrastructure.google_calendar_client import FakeGoogleCalendarClient
from app.modules.appointment.infrastructure.repository import (
    AvailabilityCheckRepository,
    BrokerRepository,
)
from app.modules.conversation_ownership.application.scheduling_turn import (
    extract_confirmed_slot,
    run_scheduling_turn,
)
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.lead_qualification.domain.models import Lead
from app.modules.lead_qualification.infrastructure.repository import LeadRepository
from app.modules.lead_qualification.infrastructure.wacrm_client import WacrmLeadSnapshot
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.infrastructure.db_models import PropertyORM, RecommendationORM
from app.shared.domain.base import new_id, utcnow

REFERENCE_NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)  # a Monday


# --- extract_confirmed_slot -------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("sí, el 15/08 a las 3pm me viene bien", datetime(2026, 8, 15, 15, 0, tzinfo=UTC)),
        ("el lunes a las 10am", datetime(2026, 8, 17, 10, 0, tzinfo=UTC)),
        ("mañana a las 9am", datetime(2026, 8, 11, 9, 0, tzinfo=UTC)),
        ("hoy a las 5pm", datetime(2026, 8, 10, 17, 0, tzinfo=UTC)),
        ("perfecto, el 20/08 a las 14:30", datetime(2026, 8, 20, 14, 30, tzinfo=UTC)),
    ],
)
def test_extract_confirmed_slot_recognizes_explicit_and_relative_slots(text, expected):
    assert extract_confirmed_slot(text, reference_now=REFERENCE_NOW) == expected


@pytest.mark.parametrize(
    "text",
    [
        "me interesa esa propiedad",
        "15/08",  # date without time
        "a las 3pm",  # time without date
        "quiero comprar un departamento",
    ],
)
def test_extract_confirmed_slot_returns_none_without_a_full_slot(text):
    assert extract_confirmed_slot(text, reference_now=REFERENCE_NOW) is None


# --- run_scheduling_turn -----------------------------------------------------


SLOT_TEXT = "el 15/08 a las 3pm"
SLOT = datetime(2026, 8, 15, 15, 0, tzinfo=UTC)


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded_org(session_factory, org_id):
    async with session_factory() as session:
        session.add(
            OrganizationORM(id=org_id, name="Org Test", status="active", created_at=utcnow())
        )
        await session.commit()
    return org_id


@pytest.fixture
async def seeded_lead(session_factory, seeded_org):
    lead_id = new_id()
    async with session_factory() as session:
        lead = Lead(
            id=lead_id,
            organization_id=seeded_org,
            crm_lead_id="lead-212",
            contact_reference="+51999888777",
        )
        await LeadRepository(session).add(lead)
        await session.commit()
    return lead_id


@pytest.fixture
async def seeded_property(session_factory, seeded_org):
    property_id = new_id()
    async with session_factory() as session:
        session.add(
            PropertyORM(
                id=property_id,
                organization_id=seeded_org,
                external_id="prop-212",
                price=250000.0,
                zone="Miraflores",
                property_type="apartment",
                features=[],
                description="",
                name_address="Av. Test 123",
                estado="disponible",
                link_references=[],
                updated_at=utcnow(),
            )
        )
        await session.commit()
    return property_id


async def _seed_recommendation(session_factory, org_id, lead_id, property_id, *, rank=1):
    async with session_factory() as session:
        session.add(
            RecommendationORM(
                id=new_id(),
                organization_id=org_id,
                lead_id=lead_id,
                buyer_profile_id=None,
                property_id=property_id,
                rank=rank,
                score=0.9,
                signals=[],
                explanation="matches budget and zone",
                neighborhood=None,
                feedback=None,
                generated_at=utcnow(),
                delivered_at=None,
            )
        )
        await session.commit()


async def _seed_active_broker(session_factory, org_id):
    async with session_factory() as session:
        broker = Broker(organization_id=org_id, active=True)
        await BrokerRepository(session).add(broker)
        await session.commit()
    return broker.id


async def _seed_confirmed_check(session_factory, org_id, property_id):
    async with session_factory() as session:
        await AvailabilityCheckRepository(session).save(
            AvailabilityCheck(
                organization_id=org_id,
                property_id=property_id,
                slot=SLOT,
                status=AvailabilityStatus.CONFIRMED,
                source=AvailabilityCheckSource.INITIAL,
            )
        )
        await session.commit()


def _make_conversation(org_id, lead_id):
    conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="212")
    conversation.link_lead(lead_id)
    return conversation


async def test_run_scheduling_turn_returns_no_slot_when_message_has_no_slot(
    session_factory, seeded_org, seeded_lead
):
    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_scheduling_turn(
            session, conversation=conversation, text="hola, cómo estás"
        )
    assert result.outcome == "no_slot"
    assert result.response is None


async def test_run_scheduling_turn_returns_no_recommendation_when_none_exists(
    session_factory, seeded_org, seeded_lead
):
    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_scheduling_turn(session, conversation=conversation, text=SLOT_TEXT)
    assert result.outcome == "no_recommendation"
    assert result.response is not None


async def test_run_scheduling_turn_returns_no_broker_when_none_active(
    session_factory, seeded_org, seeded_lead, seeded_property
):
    await _seed_recommendation(session_factory, seeded_org, seeded_lead, seeded_property)
    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_scheduling_turn(session, conversation=conversation, text=SLOT_TEXT)
    assert result.outcome == "no_broker"
    assert result.response is not None


async def test_run_scheduling_turn_returns_error_when_calendar_not_configured(
    session_factory, seeded_org, seeded_lead, seeded_property
):
    """No `google_workspace` config exists for `seeded_org` — matches
    `build_calendar_client`'s `CalendarNotConfiguredError` path (design.md
    Decision 4): the turn degrades gracefully instead of raising."""
    await _seed_recommendation(session_factory, seeded_org, seeded_lead, seeded_property)
    await _seed_active_broker(session_factory, seeded_org)
    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_scheduling_turn(session, conversation=conversation, text=SLOT_TEXT)
    assert result.outcome == "error"
    assert result.response is not None


async def test_run_scheduling_turn_not_confirmed_when_availability_is_pending(
    session_factory, seeded_org, seeded_lead, seeded_property, monkeypatch
):
    """PENDING requires no seeding — it's AvailabilityValidatorService's
    default (same as tests/test_scheduling_service.py)."""
    await _seed_recommendation(session_factory, seeded_org, seeded_lead, seeded_property)
    await _seed_active_broker(session_factory, seeded_org)
    _patch_calendar_client(monkeypatch)

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_scheduling_turn(session, conversation=conversation, text=SLOT_TEXT)

    assert result.outcome == "not_confirmed"
    assert result.appointment is None


async def test_run_scheduling_turn_books_appointment_on_confirmed_availability(
    session_factory, seeded_org, seeded_lead, seeded_property, monkeypatch
):
    await _seed_recommendation(session_factory, seeded_org, seeded_lead, seeded_property)
    await _seed_active_broker(session_factory, seeded_org)
    await _seed_confirmed_check(session_factory, seeded_org, seeded_property)
    _patch_calendar_client(monkeypatch)

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_scheduling_turn(session, conversation=conversation, text=SLOT_TEXT)
        await session.commit()

    assert result.outcome == "booked"
    assert result.appointment is not None
    assert result.appointment.status.value == "booked"
    assert "meet.google.com" in result.response

    async with session_factory() as session:
        from app.modules.lead_qualification.infrastructure.db_models import LeadORM

        lead_row = await session.get(LeadORM, seeded_lead)
        assert lead_row.pipeline_stage == "AppointmentSet"


class _FakeWacrmClient:
    """Minimal in-memory stand-in, same shape as
    tests/test_scheduling_service.py's `FakeWacrmClient` — avoids a real HTTP
    call to the (unavailable in tests) wacrm mock server."""

    def __init__(self):
        self.stage_updates: list[tuple[str, str]] = []

    async def update_stage(self, crm_lead_id, pipeline_stage, assigned_broker_id=None):
        self.stage_updates.append((crm_lead_id, pipeline_stage))
        return WacrmLeadSnapshot(
            crm_lead_id=crm_lead_id,
            organization_id=new_id(),
            pipeline_stage=pipeline_stage,
            assigned_broker_id=None,
            lead_score=0.0,
            updated_at=utcnow(),
            contact_reference=None,
        )


def _patch_calendar_client(monkeypatch):
    """`build_calendar_client` needs a `google_workspace` config this test
    suite doesn't seed — patch the wiring seam directly rather than building
    real `OrganizationConfig`/service-account fixtures, mirroring how
    `_build_service` in tests/test_scheduling_service.py injects a
    `FakeGoogleCalendarClient`. Also patches `build_wacrm_client` for the same
    reason — no `CrmConfig` is seeded, so the real client would hit an
    unreachable `localhost` mock server."""

    async def _fake_build_calendar_client(session, organization_id):
        return FakeGoogleCalendarClient(
            result=CalendarEventResult(
                calendar_event_id="evt-212", meet_link="https://meet.google.com/x212"
            )
        )

    async def _fake_build_wacrm_client(session, organization_id):
        return _FakeWacrmClient()

    monkeypatch.setattr(
        "app.modules.conversation_ownership.application.scheduling_turn.build_calendar_client",
        _fake_build_calendar_client,
    )
    monkeypatch.setattr(
        "app.modules.conversation_ownership.application.scheduling_turn.build_wacrm_client",
        _fake_build_wacrm_client,
    )


# --- US-220: lead-selected property takes priority over rank-1 --------------


async def test_latest_top_pick_prefers_lead_selected_property_over_rank_one(
    session_factory, seeded_org, seeded_lead, monkeypatch
):
    """US-220: once `RecommendationRepository.mark_selected` flags a non-rank-1
    property in the batch, `run_scheduling_turn` SHALL book that property, not
    the pipeline's original rank-1 default — the routing mechanism the
    deepening turn relies on."""
    from app.modules.appointment.infrastructure.repository import BrokerRepository
    from app.modules.recommendation.infrastructure.repository import RecommendationRepository

    rank1_property = await _seed_property_row(session_factory, seeded_org, external_id="prop-r1")
    rank2_property = await _seed_property_row(session_factory, seeded_org, external_id="prop-r2")
    generated_at = utcnow()
    async with session_factory() as session:
        session.add(
            RecommendationORM(
                id=new_id(),
                organization_id=seeded_org,
                lead_id=seeded_lead,
                buyer_profile_id=None,
                property_id=rank1_property,
                rank=1,
                score=0.9,
                signals=[],
                explanation="rank 1",
                neighborhood=None,
                feedback=None,
                generated_at=generated_at,
                delivered_at=None,
            )
        )
        session.add(
            RecommendationORM(
                id=new_id(),
                organization_id=seeded_org,
                lead_id=seeded_lead,
                buyer_profile_id=None,
                property_id=rank2_property,
                rank=2,
                score=0.8,
                signals=[],
                explanation="rank 2",
                neighborhood=None,
                feedback=None,
                generated_at=generated_at,
                delivered_at=None,
            )
        )
        await session.commit()

    async with session_factory() as session:
        await RecommendationRepository(session).mark_selected(
            seeded_lead, rank2_property, generated_at
        )
        await session.commit()

    broker = Broker(organization_id=seeded_org, active=True)
    async with session_factory() as session:
        await BrokerRepository(session).add(broker)
        await session.commit()
    await _seed_confirmed_check(session_factory, seeded_org, rank2_property)
    _patch_calendar_client(monkeypatch)

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_scheduling_turn(session, conversation=conversation, text=SLOT_TEXT)
        await session.commit()

    assert result.outcome == "booked"
    assert result.appointment.property_id == rank2_property


async def _seed_property_row(session_factory, org_id, *, external_id: str):
    property_id = new_id()
    async with session_factory() as session:
        session.add(
            PropertyORM(
                id=property_id,
                organization_id=org_id,
                external_id=external_id,
                price=250000.0,
                zone="Miraflores",
                property_type="apartment",
                features=[],
                description="",
                name_address=f"Av. {external_id} 123",
                estado="disponible",
                link_references=[],
                updated_at=utcnow(),
            )
        )
        await session.commit()
    return property_id
