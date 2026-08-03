"""US-212: integration coverage for the wiring itself — `CoordinatorAgent`
invoking `SchedulingService`/`AvailabilityValidatorService` through
`run_scheduling_turn` when `conversation.state is ConversationState.RECOMMENDATION`.
Follows the same `CoordinatorAgent(...)` harness as
tests/test_coordinator_qualification_turn.py and the broker/availability
seeding pattern from tests/test_scheduling_service.py."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

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
from app.modules.conversation_ownership.application.coordinator import CoordinatorAgent
from app.modules.conversation_ownership.domain.models import Conversation, ConversationState
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.lead_qualification.domain.models import Lead
from app.modules.lead_qualification.infrastructure.db_models import LeadORM
from app.modules.lead_qualification.infrastructure.repository import LeadRepository
from app.modules.lead_qualification.infrastructure.wacrm_client import WacrmLeadSnapshot
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.infrastructure.db_models import PropertyORM, RecommendationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM

SLOT_TEXT = "el 15/08 a las 3pm"
SLOT = datetime(2026, 8, 15, 15, 0, tzinfo=UTC)


class StubResponder:
    def __init__(self):
        self.calls = 0

    async def respond(self, *, system_prompt: str, conversation_id, text: str) -> str:
        self.calls += 1
        return "respuesta plantilla"


class _FakeWacrmClient:
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


def _patch_scheduling_seams(monkeypatch):
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


async def _seed_recommendation_conversation(session_factory):
    """A lead + conversation already in RECOMMENDATION, with a Top-1
    recommendation and an active broker — the preconditions US-212's Gherkin
    ("Given Conversation State = Recommendation... y un horario ya validado")
    assumes exist before the lead confirms."""
    org_id = new_id()
    property_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        session.add(
            PropertyORM(
                id=property_id,
                organization_id=org_id,
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
        lead = Lead(
            organization_id=org_id, crm_lead_id="lead-212-coord", contact_reference="+51999888777"
        )
        await LeadRepository(session).add(lead)
        session.add(
            RecommendationORM(
                id=new_id(),
                organization_id=org_id,
                lead_id=lead.id,
                buyer_profile_id=None,
                property_id=property_id,
                rank=1,
                score=0.9,
                signals=[],
                explanation="matches budget and zone",
                neighborhood=None,
                feedback=None,
                generated_at=utcnow(),
                delivered_at=None,
            )
        )
        broker = Broker(organization_id=org_id, active=True)
        await BrokerRepository(session).add(broker)

        conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="212")
        conversation.link_lead(lead.id)
        conversation.transition_to(ConversationState.AI_OWNED, reason="test setup")
        conversation.transition_to(ConversationState.QUALIFICATION, reason="test setup")
        conversation.transition_to(ConversationState.RECOMMENDATION, reason="test setup")
        await ConversationRepository(session).add(conversation)
        await session.commit()
        return org_id, conversation.id, lead.id, property_id


async def _handle(session_factory, org_id, conversation_id, text, responder=None):
    responder = responder or StubResponder()
    async with session_factory() as session:
        agent = CoordinatorAgent(session, responder=responder)
        await agent.handle_message(
            organization_id=org_id, conversation_id=conversation_id, text=text
        )
    return responder


async def test_coordinator_books_appointment_and_transitions_to_appointment_state(
    session_factory, monkeypatch
):
    _patch_scheduling_seams(monkeypatch)
    org_id, conversation_id, lead_id, property_id = await _seed_recommendation_conversation(
        session_factory
    )
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

    responder = await _handle(session_factory, org_id, conversation_id, SLOT_TEXT)
    assert responder.calls == 0  # short-circuited — the LLM never ran this turn

    async with session_factory() as session:
        conversation = await ConversationRepository(session).get(conversation_id)
        assert conversation.state is ConversationState.APPOINTMENT

        lead_row = await session.get(LeadORM, lead_id)
        assert lead_row.pipeline_stage == "AppointmentSet"

        outbox = (await session.execute(select(OutboxEventORM))).scalars().all()
        assert any(row.event_type == "AppointmentBooked" for row in outbox)
        response_events = [row for row in outbox if row.event_type == "ResponseReady"]
        assert len(response_events) == 1
        assert "meet.google.com" in response_events[0].payload["fields"]["response"]


async def test_coordinator_falls_back_gracefully_when_availability_still_pending(
    session_factory, monkeypatch
):
    """PENDING requires no seeding — AvailabilityValidatorService's default."""
    _patch_scheduling_seams(monkeypatch)
    org_id, conversation_id, lead_id, _property_id = await _seed_recommendation_conversation(
        session_factory
    )

    responder = await _handle(session_factory, org_id, conversation_id, SLOT_TEXT)
    assert responder.calls == 0  # scheduling short-circuits even the fallback reply

    async with session_factory() as session:
        conversation = await ConversationRepository(session).get(conversation_id)
        assert conversation.state is ConversationState.RECOMMENDATION  # unchanged

        lead_row = await session.get(LeadORM, lead_id)
        assert lead_row.pipeline_stage != "AppointmentSet"

        outbox = (await session.execute(select(OutboxEventORM))).scalars().all()
        assert not any(row.event_type == "AppointmentBooked" for row in outbox)


async def test_coordinator_message_without_slot_falls_through_to_responder(
    session_factory, monkeypatch
):
    """Aditive-only contract: a message carrying no recognizable slot must
    not touch scheduling at all — the normal `ResponderPort` reply happens,
    same as before this change existed."""
    _patch_scheduling_seams(monkeypatch)
    org_id, conversation_id, _lead_id, _property_id = await _seed_recommendation_conversation(
        session_factory
    )

    responder = await _handle(
        session_factory, org_id, conversation_id, "¿Tiene cochera esa propiedad?"
    )
    assert responder.calls == 1

    async with session_factory() as session:
        conversation = await ConversationRepository(session).get(conversation_id)
        assert conversation.state is ConversationState.RECOMMENDATION


# --- US-220: deepening turn end-to-end through the coordinator --------------


async def _seed_multi_item_recommendation_conversation(session_factory):
    """Same shape as `_seed_recommendation_conversation` but with a 3-item
    Top-3 batch, the precondition US-220's deepening turn requires (a
    single-property batch has nothing to deepen on, see
    tests/test_deepening_turn.py)."""
    org_id = new_id()
    property_ids = [new_id(), new_id(), new_id()]
    generated_at = utcnow()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        for i, property_id in enumerate(property_ids, start=1):
            session.add(
                PropertyORM(
                    id=property_id,
                    organization_id=org_id,
                    external_id=f"prop-220-{i}",
                    price=250000.0,
                    zone="Miraflores",
                    property_type="apartment",
                    features=[],
                    description="",
                    name_address=f"Av. Test {i}",
                    estado="disponible",
                    link_references=[],
                    updated_at=utcnow(),
                )
            )
        lead = Lead(
            organization_id=org_id, crm_lead_id="lead-220-coord", contact_reference="+51999888777"
        )
        await LeadRepository(session).add(lead)
        for rank, property_id in enumerate(property_ids, start=1):
            session.add(
                RecommendationORM(
                    id=new_id(),
                    organization_id=org_id,
                    lead_id=lead.id,
                    buyer_profile_id=None,
                    property_id=property_id,
                    rank=rank,
                    score=1.0 - (rank * 0.1),
                    signals=[],
                    explanation=f"matches criteria (rank {rank})",
                    neighborhood=None,
                    feedback=None,
                    generated_at=generated_at,
                    delivered_at=None,
                )
            )
        broker = Broker(organization_id=org_id, active=True)
        await BrokerRepository(session).add(broker)

        conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="220")
        conversation.link_lead(lead.id)
        conversation.transition_to(ConversationState.AI_OWNED, reason="test setup")
        conversation.transition_to(ConversationState.QUALIFICATION, reason="test setup")
        conversation.transition_to(ConversationState.RECOMMENDATION, reason="test setup")
        await ConversationRepository(session).add(conversation)
        await session.commit()
        return org_id, conversation.id, lead.id, property_ids


async def test_coordinator_asks_deepening_question_before_scheduling_on_multi_item_batch(
    session_factory, monkeypatch
):
    _patch_scheduling_seams(monkeypatch)
    org_id, conversation_id, _lead_id, _property_ids = (
        await _seed_multi_item_recommendation_conversation(session_factory)
    )

    responder = await _handle(
        session_factory, org_id, conversation_id, "me gustaron todas, no sé cuál elegir"
    )
    assert responder.calls == 0  # deepening question short-circuits the LLM

    async with session_factory() as session:
        outbox = (await session.execute(select(OutboxEventORM))).scalars().all()
        response_events = [row for row in outbox if row.event_type == "ResponseReady"]
        assert len(response_events) == 1
        assert "opci" in response_events[0].payload["fields"]["response"].lower()

        conversation = await ConversationRepository(session).get(conversation_id)
        assert conversation.state is ConversationState.RECOMMENDATION


async def test_coordinator_selection_then_slot_books_the_selected_non_rank1_property(
    session_factory, monkeypatch
):
    """End-to-end US-212 <-> US-220 handoff: the lead names option 2 in one
    turn, then confirms a slot in a later turn — the booked appointment SHALL
    target the rank-2 property, not the pipeline's rank-1 default."""
    _patch_scheduling_seams(monkeypatch)
    org_id, conversation_id, lead_id, property_ids = (
        await _seed_multi_item_recommendation_conversation(session_factory)
    )
    rank2_property = property_ids[1]

    async with session_factory() as session:
        await AvailabilityCheckRepository(session).save(
            AvailabilityCheck(
                organization_id=org_id,
                property_id=rank2_property,
                slot=SLOT,
                status=AvailabilityStatus.CONFIRMED,
                source=AvailabilityCheckSource.INITIAL,
            )
        )
        await session.commit()

    first_responder = await _handle(session_factory, org_id, conversation_id, "la opción 2 se ve bien")
    assert first_responder.calls == 1  # selection recorded, turn falls through normally

    second_responder = await _handle(session_factory, org_id, conversation_id, SLOT_TEXT)
    assert second_responder.calls == 0  # scheduling short-circuits, as usual

    async with session_factory() as session:
        conversation = await ConversationRepository(session).get(conversation_id)
        assert conversation.state is ConversationState.APPOINTMENT

        outbox = (await session.execute(select(OutboxEventORM))).scalars().all()
        response_events = [row for row in outbox if row.event_type == "ResponseReady"]
        assert "meet.google.com" in response_events[-1].payload["fields"]["response"]

        rows = (
            await session.execute(
                RecommendationORM.__table__.select().where(
                    RecommendationORM.lead_id == lead_id, RecommendationORM.property_id == rank2_property
                )
            )
        ).first()
        assert rows.feedback == {"selected_by_lead": True}
