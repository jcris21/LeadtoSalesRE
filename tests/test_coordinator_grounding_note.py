"""2026-07-25 follow-up to US-hallucination-fix (2026-07-24): the original fix
only re-ran the real structured filter (`search_diagnostics.diagnose`) on the
turn that just captured a new budget/zone dimension. The very next turn — no
new dimension that turn — got no grounding at all, and the LLM (primed by its
own prior "en breve tendrás el Top-3" line) invented three full listings.
`_build_grounding_note` now gates on conversation stage (Qualification) plus
"does the profile already have a budget or zone", not on "did this turn's
message carry a new signal" — this covers the exact follow-up-turn gap."""

import uuid

import pytest

from app.modules.conversation_ownership.application.coordinator import CoordinatorAgent
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    Lead,
    MoneyRange,
    PropertyType,
)
from app.modules.lead_qualification.infrastructure.repository import (
    BuyerProfileRepository,
    LeadRepository,
)
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.domain.models import Property
from app.modules.recommendation.infrastructure.repository import PropertyRepository
from app.shared.domain.base import new_id, utcnow


class NoSignalExtractor:
    """This turn's message carries no new qualification signal — the exact
    shape of the follow-up turn that used to skip grounding entirely."""

    async def extract(self, *, text: str, missing_dimensions: tuple[str, ...]):
        return None


class CapturingResponder:
    """Records the system_prompt handed to it each turn, so the test can
    assert whether a grounding note was appended."""

    def __init__(self, reply: str = "respuesta") -> None:
        self.reply = reply
        self.system_prompts: list[str] = []

    async def respond(self, *, system_prompt: str, conversation_id, text: str) -> str:
        self.system_prompts.append(system_prompt)
        return self.reply


async def _seed_conversation_with_existing_profile(session_factory):
    org_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        lead = Lead(organization_id=org_id, crm_lead_id="lead-1")
        await LeadRepository(session).add(lead)

        # Budget + zone were captured in a PRIOR turn — already on the profile
        # before this test's turn runs.
        profile = BuyerProfile(
            lead_id=lead.id,
            budget=MoneyRange(minimum=200_000, maximum=300_000),
            locations=("Miraflores",),
            property_type=PropertyType.APARTMENT,
        )
        await BuyerProfileRepository(session).save(org_id, profile)

        await PropertyRepository(session).upsert(
            Property(
                organization_id=org_id,
                external_id=str(uuid.uuid4()),
                price=245_000.0,
                zone="Miraflores",
                property_type=PropertyType.APARTMENT,
                link_references=("https://demo.realestate/listing/1",),
            )
        )

        conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="99")
        conversation.link_lead(lead.id)
        await ConversationRepository(session).add(conversation)
        await session.commit()
        return org_id, conversation.id


@pytest.mark.asyncio
async def test_grounding_note_fires_on_follow_up_turn_with_no_new_dimension(session_factory):
    org_id, conversation_id = await _seed_conversation_with_existing_profile(session_factory)
    responder = CapturingResponder()

    async with session_factory() as session:
        agent = CoordinatorAgent(
            session, responder=responder, generative_extractor=NoSignalExtractor()
        )
        await agent.handle_message(
            organization_id=org_id, conversation_id=conversation_id, text="Perfecto, gracias"
        )
        await session.commit()

    assert len(responder.system_prompts) == 1
    assert "Contexto interno" in responder.system_prompts[0]
    assert "SÍ hay propiedades disponibles" in responder.system_prompts[0]
