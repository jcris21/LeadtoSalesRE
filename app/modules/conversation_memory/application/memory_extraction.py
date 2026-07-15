"""Conversation Memory extraction (AI-102): turns a lead's free text into
zero or more `ConversationMemoryObservation` rows.

Deterministic Spanish keyword matching — no LLM call is wired yet (see
design.md's Non-Goals: this is a documented scoped-down first cut even though
free-text style/tone signal is, by nature, a stronger long-term candidate for
LLM extraction than `qualification_flow.py`'s closed-enum dimensions).

Unlike `extract_objection` (US-209, single best match), a message can carry
both a style cue and a family-context cue at once, so this extractor returns
a list, inserting one row per detected signal (design.md Decision 3).

Tenant isolation: verifies the lead belongs to `organization_id` before
persisting, mirroring `qualification_flow.py`'s `_assert_tenant`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation_memory.domain.models import (
    ConversationMemoryObservation,
    MemoryType,
)
from app.modules.conversation_memory.infrastructure.repository import (
    ConversationMemoryRepository,
)
from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.infrastructure.repository import LeadRepository

#: Fixed placeholder confidence for every keyword-matched observation
#: (design.md Decision 4) — not a computed probability. Signals "first-cut /
#: deterministic" provenance to a future consumer once an LLM-backed
#: extractor coexists and reports genuine model confidence.
_KEYWORD_MATCH_CONFIDENCE = 0.6

_STYLE_KEYWORDS: tuple[str, ...] = (
    "minimalista",
    "luminoso",
    "luminosa",
    "moderno",
    "moderna",
    "clasico",
    "clasica",
    "acogedor",
    "acogedora",
    "elegante",
    "rustico",
    "rustica",
    "contemporaneo",
    "contemporanea",
)

_FAMILY_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "tenemos hijos",
    "tenemos ninos",
    "tenemos niños",
    "vivimos solos",
    "somos una pareja sin hijos",
    "tenemos mascota",
    "tenemos una mascota",
)


def _strip_accents(text: str) -> str:
    replacements = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
    for accented, plain in replacements.items():
        text = text.replace(accented, plain)
    return text


def _normalize(text: str) -> str:
    return _strip_accents(text.lower())


async def _assert_tenant(
    session: AsyncSession, lead_id: uuid.UUID, organization_id: uuid.UUID
) -> None:
    lead = await LeadRepository(session).get(lead_id)
    if lead is None or lead.organization_id != organization_id:
        raise LeadNotFoundError(lead_id)


def _find_style_keywords(normalized_text: str) -> tuple[str, ...]:
    return tuple(kw for kw in _STYLE_KEYWORDS if _normalize(kw) in normalized_text)


def _find_family_context_keywords(normalized_text: str) -> tuple[str, ...]:
    return tuple(kw for kw in _FAMILY_CONTEXT_KEYWORDS if _normalize(kw) in normalized_text)


async def extract_conversation_memory(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> list[ConversationMemoryObservation]:
    """AI-102: detects style-preference and family-context signals in free
    text and persists one `ConversationMemoryObservation` row per detected
    signal. Never touches `BuyerProfile`/`PROFILE_DIMENSIONS`."""
    normalized = _normalize(text)
    style_matches = _find_style_keywords(normalized)
    family_matches = _find_family_context_keywords(normalized)
    if not style_matches and not family_matches:
        return []

    await _assert_tenant(session, lead_id, organization_id)
    repository = ConversationMemoryRepository(session)
    observations: list[ConversationMemoryObservation] = []

    if style_matches:
        observation = ConversationMemoryObservation(
            conversation_id=conversation_id,
            lead_id=lead_id,
            organization_id=organization_id,
            memory_type=MemoryType.STYLE_PREFERENCE,
            entity_name="estilo_interior",
            value={"adjectives": list(style_matches), "raw_text": text},
            confidence=_KEYWORD_MATCH_CONFIDENCE,
        )
        await repository.add(observation)
        observations.append(observation)

    if family_matches:
        observation = ConversationMemoryObservation(
            conversation_id=conversation_id,
            lead_id=lead_id,
            organization_id=organization_id,
            memory_type=MemoryType.FAMILY_CONTEXT,
            entity_name="contexto_familiar",
            value={"phrases": list(family_matches), "raw_text": text},
            confidence=_KEYWORD_MATCH_CONFIDENCE,
        )
        await repository.add(observation)
        observations.append(observation)

    return observations
