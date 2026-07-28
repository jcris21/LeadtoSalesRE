"""G1 (docs/e2e-manual-chat-checklist.md): the Coordinator extracts the
qualification dimensions directly from the lead's chat messages — no QA
endpoint involved. Covers the full E2E message script, the budget routing
guard, re-prompt override, objection capture, the unlinked-conversation skip
and the generative fallback trigger condition."""

import pytest
from sqlalchemy import select

from app.modules.conversation_ownership.application.coordinator import CoordinatorAgent
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.lead_qualification.application.qualification_flow import _REPROMPT_BUDGET
from app.modules.lead_qualification.domain.models import (
    DecisionMakerMode,
    FinancingType,
    Lead,
    Motivation,
    MoneyRange,
    ProfilePatch,
    PropertyType,
    Timeline,
)
from app.modules.lead_qualification.infrastructure.db_models import LeadObjectionORM
from app.modules.lead_qualification.infrastructure.repository import (
    BuyerProfileRepository,
    LeadRepository,
)
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM


class StubResponder:
    async def respond(self, *, system_prompt: str, conversation_id, text: str) -> str:
        return "respuesta plantilla"


class NoSignalExtractor:
    """Generative stub that never recognizes anything — keeps tests hermetic
    even when a real GEMINI_API_KEY is present in the local .env."""

    def __init__(self):
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def extract(self, *, text: str, missing_dimensions: tuple[str, ...]):
        self.calls.append((text, missing_dimensions))
        return None


class FixedPatchExtractor(NoSignalExtractor):
    def __init__(self, patch: ProfilePatch):
        super().__init__()
        self._patch = patch

    async def extract(self, *, text: str, missing_dimensions: tuple[str, ...]):
        self.calls.append((text, missing_dimensions))
        return self._patch


async def _seed_linked_conversation(session_factory):
    org_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        lead = Lead(organization_id=org_id, crm_lead_id="lead-1")
        await LeadRepository(session).add(lead)
        conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="77")
        conversation.link_lead(lead.id)
        await ConversationRepository(session).add(conversation)
        await session.commit()
        return org_id, conversation.id, lead.id


async def _handle(session_factory, org_id, conversation_id, text, extractor=None):
    async with session_factory() as session:
        agent = CoordinatorAgent(
            session,
            responder=StubResponder(),
            generative_extractor=extractor or NoSignalExtractor(),
        )
        await agent.handle_message(
            organization_id=org_id, conversation_id=conversation_id, text=text
        )


#: The manual E2E script (checklist §6, scenario A) — pure chat, no endpoints.
E2E_SCRIPT = (
    "Hola! buenas tardes",
    "Estoy buscando un departamento para comprar",
    "Que tenga 2 dormitorios por favor",
    "Me interesa la zona de Miraflores o San Isidro",
    "Mi presupuesto es de 200 mil a 300 mil dolares",
    "Quisiera mudarme en 3 meses como maximo",
    "Es indispensable que tenga cochera y balcon",
    "Ya tengo un credito hipotecario aprobado en el banco",
    "La decision la tomo junto con mi esposa",
)


@pytest.mark.asyncio
async def test_e2e_script_fills_profile_and_fires_profile_completed(session_factory):
    org_id, conversation_id, lead_id = await _seed_linked_conversation(session_factory)

    for message in E2E_SCRIPT:
        await _handle(session_factory, org_id, conversation_id, message)

    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(lead_id)
        assert profile is not None
        assert profile.completeness() == 100.0
        # "en 3 meses" must have landed as timeline, never as budget (guard);
        # likewise "2 dormitorios" is the only message that may set bedrooms.
        assert profile.budget == MoneyRange(minimum=200000.0, maximum=300000.0)
        assert profile.bedrooms == 2
        assert set(profile.locations) == {"Miraflores", "San Isidro"}
        assert profile.property_type is PropertyType.APARTMENT
        assert profile.timeline is Timeline.THREE_MONTHS
        assert profile.must_haves == ("cochera", "balcon")
        assert profile.financing_type is FinancingType.MORTGAGE_APPROVED
        assert profile.decision_maker_mode is DecisionMakerMode.COUPLE
        # "Quisiera mudarme en 3 meses" also carries a relocation signal (US-219).
        assert profile.motivation is Motivation.RELOCATION

        completed = (
            (
                await session.execute(
                    select(OutboxEventORM).where(
                        OutboxEventORM.event_type == "ProfileCompleted"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(completed) == 1  # fired exactly once, on crossing the threshold


@pytest.mark.asyncio
async def test_unlinked_conversation_skips_extraction_but_still_replies(session_factory):
    org_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="88")
        await ConversationRepository(session).add(conversation)
        await session.commit()
        conversation_id = conversation.id

    extractor = NoSignalExtractor()
    await _handle(
        session_factory, org_id, conversation_id, "Busco un departamento en Surco", extractor
    )

    async with session_factory() as session:
        responses = (
            (
                await session.execute(
                    select(OutboxEventORM).where(OutboxEventORM.event_type == "ResponseReady")
                )
            )
            .scalars()
            .all()
        )
        assert len(responses) == 1  # the reply still happened
    assert extractor.calls == []  # no lead linked -> no extraction at all


@pytest.mark.asyncio
async def test_invalid_budget_signal_reprompts_instead_of_template(session_factory):
    org_id, conversation_id, _ = await _seed_linked_conversation(session_factory)

    await _handle(session_factory, org_id, conversation_id, "Mi presupuesto es 0")

    async with session_factory() as session:
        response = (
            (
                await session.execute(
                    select(OutboxEventORM).where(OutboxEventORM.event_type == "ResponseReady")
                )
            )
            .scalars()
            .one()
        )
        assert response.payload["fields"]["response"] == _REPROMPT_BUDGET


@pytest.mark.asyncio
async def test_objection_is_recorded_from_chat(session_factory):
    org_id, conversation_id, lead_id = await _seed_linked_conversation(session_factory)

    await _handle(
        session_factory, org_id, conversation_id, "Me parece muy caro, se me va del presupuesto"
    )

    async with session_factory() as session:
        objections = (
            (
                await session.execute(
                    select(LeadObjectionORM).where(LeadObjectionORM.lead_id == lead_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(objections) == 1
        assert objections[0].type == "precio"


@pytest.mark.asyncio
async def test_generative_fallback_runs_only_on_keyword_mismatch(session_factory):
    org_id, conversation_id, lead_id = await _seed_linked_conversation(session_factory)
    extractor = FixedPatchExtractor(ProfilePatch(property_type=PropertyType.APARTMENT))

    # No deterministic keyword matches -> the generative fallback classifies.
    await _handle(
        session_factory,
        org_id,
        conversation_id,
        "algo chico para vivir yo cerca del mar",
        extractor,
    )
    assert len(extractor.calls) == 1
    _, missing = extractor.calls[0]
    assert "property_type" in missing

    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(lead_id)
        assert profile.property_type is PropertyType.APARTMENT

    # Deterministic hit ("credito hipotecario aprobado") -> no fallback call.
    await _handle(
        session_factory,
        org_id,
        conversation_id,
        "tengo credito hipotecario aprobado",
        extractor,
    )
    assert len(extractor.calls) == 1
