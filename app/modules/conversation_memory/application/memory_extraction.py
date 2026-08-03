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

#: Phrases that indicate the absence of children. Checked before the
#: presence phrases so that "no tenemos hijos" is never also counted as a
#: "tenemos hijos" match (see `_find_family_context_keywords`).
_FAMILY_NO_CHILDREN_KEYWORDS: tuple[str, ...] = (
    "no tenemos hijos",
    "no tengo hijos",
    "sin hijos",
    "somos una pareja sin hijos",
)

_FAMILY_CHILDREN_PRESENCE_KEYWORDS: tuple[str, ...] = (
    "tenemos hijos",
    "tenemos hijas",
    "tenemos ninos",
    "tenemos niños",
    "tenemos ninas",
    "tenemos niñas",
    "tengo hijos",
    "tengo hijas",
    "tengo un hijo",
    "tengo una hija",
)

_FAMILY_SOLO_KEYWORDS: tuple[str, ...] = (
    "vivimos solos",
    "vivimos solas",
    "vivo solo",
    "vivo sola",
)

_FAMILY_PET_KEYWORDS: tuple[str, ...] = (
    "tenemos mascota",
    "tenemos mascotas",
    "tenemos una mascota",
    "tengo mascota",
    "tengo una mascota",
)

#: Flat union kept for compatibility with anything iterating "all family
#: context keywords" — extraction itself uses the four typed tuples above
#: via `_find_family_context_keywords`.
_FAMILY_CONTEXT_KEYWORDS: tuple[str, ...] = (
    _FAMILY_NO_CHILDREN_KEYWORDS
    + _FAMILY_CHILDREN_PRESENCE_KEYWORDS
    + _FAMILY_SOLO_KEYWORDS
    + _FAMILY_PET_KEYWORDS
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
    """Substring match against the four family-context keyword tuples.

    Negative phrases ("no tenemos hijos") are checked first; any children-
    presence phrase that is itself a substring of an already-matched
    negative phrase is dropped, so "no tenemos hijos" is never also reported
    as a "tenemos hijos" (positive) match.
    """
    negative_matches = tuple(
        kw for kw in _FAMILY_NO_CHILDREN_KEYWORDS if _normalize(kw) in normalized_text
    )
    negative_normalized = tuple(_normalize(kw) for kw in negative_matches)
    presence_matches = tuple(
        kw
        for kw in _FAMILY_CHILDREN_PRESENCE_KEYWORDS
        if _normalize(kw) in normalized_text
        and not any(_normalize(kw) in neg for neg in negative_normalized)
    )
    solo_matches = tuple(kw for kw in _FAMILY_SOLO_KEYWORDS if _normalize(kw) in normalized_text)
    pet_matches = tuple(kw for kw in _FAMILY_PET_KEYWORDS if _normalize(kw) in normalized_text)
    return negative_matches + presence_matches + solo_matches + pet_matches


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
