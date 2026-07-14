"""Qualification Flow — Prompt Chaining sub-prompts (Agentic_System.md pattern
#1) that turn a lead's WhatsApp message into a `ProfilePatch` and persist it via
`BuyerProfileCaptureService.update_profile`.

Extraction here is deterministic keyword/regex matching — no LLM call is wired
yet (`property_type` never needs one per the design; `budget`/`locations`/
`timeline`/`must_haves` are simple enough for a first cut). Swapping any of
these for an LLM-backed extractor later only changes the body of that one
function; the signature (message in, `ExtractionResult` out, persisted as a
side effect) stays the same for callers (the future Coordinator Agent).

Each extractor returns:
  - `ProfilePatch` — a signal was confidently extracted and already persisted.
  - `str` — a signal was found but failed `ProfilePatch`/`MoneyRange`
    validation; the string is a conversational re-prompt, nothing was persisted.
  - `None` — the message carries no recognizable signal for this dimension;
    `update_profile` was not called.

Tenant isolation: every extractor verifies the lead belongs to
`organization_id` before persisting (mirrors the check `update_profile`
callers must apply — see design.md "Cross-tenant write" mitigation).
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.application.profile_capture import (
    BuyerProfileCaptureService,
)
from app.modules.lead_qualification.domain.models import (
    MoneyRange,
    ProfilePatch,
    ProfileValidationError,
    PropertyType,
    Timeline,
)
from app.modules.lead_qualification.infrastructure.repository import LeadRepository

ExtractionResult = ProfilePatch | str | None

_REPROMPT_BUDGET = (
    "No pude entender tu presupuesto. ¿Podrías indicarme un rango o monto aproximado?"
)
_REPROMPT_PROPERTY_TYPE = (
    "¿Qué tipo de propiedad buscas: departamento, casa, terreno o un local comercial?"
)

_KNOWN_ZONES: tuple[str, ...] = (
    "Miraflores",
    "San Isidro",
    "Barranco",
    "Surco",
    "Santiago de Surco",
    "La Molina",
    "San Borja",
    "Chorrillos",
    "Jesús María",
    "Lince",
    "Pueblo Libre",
    "Magdalena",
    "San Miguel",
    "Surquillo",
)

_PROPERTY_TYPE_KEYWORDS: tuple[tuple[str, PropertyType], ...] = (
    ("departamento", PropertyType.APARTMENT),
    ("depa", PropertyType.APARTMENT),
    ("apartamento", PropertyType.APARTMENT),
    ("flat", PropertyType.APARTMENT),
    ("casa", PropertyType.HOUSE),
    ("chalet", PropertyType.HOUSE),
    ("terreno", PropertyType.LAND),
    ("lote", PropertyType.LAND),
    ("parcela", PropertyType.LAND),
    ("local comercial", PropertyType.COMMERCIAL),
    ("oficina", PropertyType.COMMERCIAL),
    ("comercial", PropertyType.COMMERCIAL),
    ("negocio", PropertyType.COMMERCIAL),
)

_TIMELINE_KEYWORDS: tuple[tuple[str, Timeline], ...] = (
    ("cuanto antes", Timeline.IMMEDIATE),
    ("lo antes posible", Timeline.IMMEDIATE),
    ("inmediato", Timeline.IMMEDIATE),
    ("urgente", Timeline.IMMEDIATE),
    ("ya mismo", Timeline.IMMEDIATE),
    ("mas de 6 meses", Timeline.OVER_SIX_MONTHS),
    ("mas de seis meses", Timeline.OVER_SIX_MONTHS),
    ("6 meses", Timeline.SIX_MONTHS),
    ("seis meses", Timeline.SIX_MONTHS),
    ("3 meses", Timeline.THREE_MONTHS),
    ("tres meses", Timeline.THREE_MONTHS),
    ("solo explorando", Timeline.EXPLORING),
    ("solo viendo", Timeline.EXPLORING),
    ("sin apuro", Timeline.EXPLORING),
    ("explorando opciones", Timeline.EXPLORING),
)

_MUST_HAVE_MARKERS = (
    "indispensable que",
    "imprescindible que",
    "necesito que tenga",
    "necesita que tenga",
    "debe tener",
    "tiene que tener",
)

_RANGE_RE = re.compile(
    r"(?P<a>\d[\d.,]*)\s*(?P<au>k|mil)?\s*(?:-|a|y|hasta)\s*(?P<b>\d[\d.,]*)\s*(?P<bu>k|mil)?",
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(r"(?P<a>\d[\d.,]*)\s*(?P<au>k|mil)?", re.IGNORECASE)


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


def _parse_amount(raw: str, unit: str | None) -> float:
    cleaned = raw.replace(",", "").replace(".", "")
    value = float(cleaned)
    if unit and unit.lower() in ("k", "mil"):
        value *= 1000
    return value


def _extract_budget_range(text: str) -> tuple[float, float] | None:
    match = _RANGE_RE.search(text)
    if match:
        first = _parse_amount(match.group("a"), match.group("au"))
        second = _parse_amount(match.group("b"), match.group("bu"))
        return (first, second) if first <= second else (second, first)
    match = _SINGLE_RE.search(text)
    if match:
        amount = _parse_amount(match.group("a"), match.group("au"))
        return (amount, amount)
    return None


async def extract_budget(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> ExtractionResult:
    """US-202: budget range extraction."""
    amounts = _extract_budget_range(text)
    if amounts is None:
        return None

    minimum, maximum = amounts
    await _assert_tenant(session, lead_id, organization_id)
    try:
        patch = ProfilePatch(budget=MoneyRange(minimum=minimum, maximum=maximum))
    except ProfileValidationError:
        return _REPROMPT_BUDGET

    service = BuyerProfileCaptureService(session)
    await service.update_profile(lead_id, patch)
    return patch


async def extract_locations(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> ExtractionResult:
    """US-203: zone/district extraction."""
    normalized = _normalize(text)
    found = tuple(zone for zone in _KNOWN_ZONES if _normalize(zone) in normalized)
    # Drop "Surco" when the more specific "Santiago de Surco" is also present,
    # so the tuple doesn't carry the same district twice under two names.
    if "Santiago de Surco" in found and "Surco" in found:
        found = tuple(zone for zone in found if zone != "Surco")
    if not found:
        return None

    await _assert_tenant(session, lead_id, organization_id)
    try:
        patch = ProfilePatch(locations=found)
    except ProfileValidationError:
        return None  # unreachable: `found` is never empty here, kept for symmetry

    service = BuyerProfileCaptureService(session)
    await service.update_profile(lead_id, patch)
    return patch


async def extract_property_type(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> ExtractionResult:
    """US-204: closed-enum property type classification, keyword-first (no LLM
    call needed for the common case)."""
    normalized = _normalize(text)
    best_index: int | None = None
    best_type: PropertyType | None = None
    for keyword, property_type in _PROPERTY_TYPE_KEYWORDS:
        index = normalized.find(_normalize(keyword))
        if index != -1 and (best_index is None or index < best_index):
            best_index = index
            best_type = property_type
    if best_type is None:
        return None

    await _assert_tenant(session, lead_id, organization_id)
    try:
        patch = ProfilePatch(property_type=best_type)
    except ProfileValidationError:
        return _REPROMPT_PROPERTY_TYPE

    service = BuyerProfileCaptureService(session)
    await service.update_profile(lead_id, patch)
    return patch


def _extract_timeline(normalized_text: str) -> Timeline | None:
    for keyword, timeline in _TIMELINE_KEYWORDS:
        if _normalize(keyword) in normalized_text:
            return timeline
    return None


def _extract_must_haves(text: str, normalized_text: str) -> tuple[str, ...] | None:
    for marker in _MUST_HAVE_MARKERS:
        index = normalized_text.find(_normalize(marker))
        if index == -1:
            continue
        remainder = text[index + len(marker) :].strip(" .,:;")
        remainder = re.sub(r"^tenga\s+", "", remainder, flags=re.IGNORECASE)
        if not remainder:
            continue
        items = re.split(r",|\by\b", remainder)
        cleaned = tuple(item.strip(" .") for item in items if item.strip(" ."))
        if cleaned:
            return cleaned
    return None


async def extract_timeline_and_must_haves(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> ExtractionResult:
    """US-205: purchase timeline and/or non-negotiable requirements, both may
    be present in the same message and land in a single `ProfilePatch`."""
    normalized = _normalize(text)
    timeline = _extract_timeline(normalized)
    must_haves = _extract_must_haves(text, normalized)
    if timeline is None and must_haves is None:
        return None

    await _assert_tenant(session, lead_id, organization_id)
    try:
        patch = ProfilePatch(timeline=timeline, must_haves=must_haves)
    except ProfileValidationError:
        return None  # unreachable: both fields are None or non-empty here

    service = BuyerProfileCaptureService(session)
    await service.update_profile(lead_id, patch)
    return patch
