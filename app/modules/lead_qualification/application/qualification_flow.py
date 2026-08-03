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
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lead_qualification.application.lead_scoring import LeadScoringService
from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.application.profile_capture import (
    BuyerProfileCaptureService,
)
from app.modules.lead_qualification.domain.models import (
    DecisionMakerMode,
    FinancingType,
    MoneyRange,
    Motivation,
    ObjectionType,
    ProfilePatch,
    ProfileValidationError,
    PropertyType,
    Timeline,
)
from app.modules.lead_qualification.infrastructure.repository import LeadRepository

ExtractionResult = ProfilePatch | str | None
#: US-209: objection detection is not a `BuyerProfile` dimension, so it does
#: not go through `ProfilePatch` — the result is the matched `ObjectionType`
#: (already persisted via `LeadScoringService.record_objection`) or `None`.
ObjectionExtractionResult = ObjectionType | None

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

_FINANCING_KEYWORDS: tuple[tuple[str, FinancingType], ...] = (
    ("credito hipotecario aprobado", FinancingType.MORTGAGE_APPROVED),
    ("credito preaprobado", FinancingType.MORTGAGE_PREAPPROVED),
    ("credito pre-aprobado", FinancingType.MORTGAGE_PREAPPROVED),
    ("credito ya aprobado", FinancingType.MORTGAGE_APPROVED),
    ("hipoteca aprobada", FinancingType.MORTGAGE_APPROVED),
    ("credito hipotecario", FinancingType.MORTGAGE_APPROVED),
    ("evaluando financiamiento", FinancingType.EVALUATING),
    ("evaluando credito", FinancingType.EVALUATING),
    ("estoy evaluando como financiar", FinancingType.EVALUATING),
    ("al contado", FinancingType.CASH),
    ("de contado", FinancingType.CASH),
    ("pago en efectivo", FinancingType.CASH),
    ("contado", FinancingType.CASH),
)

_DECISION_MODE_KEYWORDS: tuple[tuple[str, DecisionMakerMode], ...] = (
    ("con mi esposa", DecisionMakerMode.COUPLE),
    ("con mi esposo", DecisionMakerMode.COUPLE),
    ("con mi pareja", DecisionMakerMode.COUPLE),
    ("en pareja", DecisionMakerMode.COUPLE),
    ("con mi familia", DecisionMakerMode.FAMILY),
    ("decision familiar", DecisionMakerMode.FAMILY),
    ("toda la familia", DecisionMakerMode.FAMILY),
    ("yo solo", DecisionMakerMode.SOLO),
    ("yo sola", DecisionMakerMode.SOLO),
    ("decido solo", DecisionMakerMode.SOLO),
    ("decido sola", DecisionMakerMode.SOLO),
    ("solo yo decido", DecisionMakerMode.SOLO),
)

#: US-219: purchase motivation, keyword-first (mirrors `_PROPERTY_TYPE_KEYWORDS`).
#: Longer/more specific phrases are listed before shorter ones so the
#: "first mention wins" scan (`_extract_motivation`) prefers the most
#: specific match when multiple keywords could overlap in the same message.
_MOTIVATION_KEYWORDS: tuple[tuple[str, Motivation], ...] = (
    ("es mi primera vivienda", Motivation.FIRST_HOME),
    ("es mi primer departamento", Motivation.FIRST_HOME),
    ("es mi primera casa", Motivation.FIRST_HOME),
    ("mi primera propiedad", Motivation.FIRST_HOME),
    ("primera vivienda", Motivation.FIRST_HOME),
    ("primer hogar", Motivation.FIRST_HOME),
    ("nos vamos a mudar", Motivation.RELOCATION),
    ("me voy a mudar", Motivation.RELOCATION),
    ("necesito mudarme", Motivation.RELOCATION),
    ("quisiera mudarme", Motivation.RELOCATION),
    ("cambio de casa", Motivation.RELOCATION),
    ("mudanza", Motivation.RELOCATION),
    ("mudarme", Motivation.RELOCATION),
    ("mudarnos", Motivation.RELOCATION),
    ("para invertir", Motivation.INVESTMENT),
    ("como inversion", Motivation.INVESTMENT),
    ("para alquilarlo", Motivation.INVESTMENT),
    ("para poner en alquiler", Motivation.INVESTMENT),
    ("inversion inmobiliaria", Motivation.INVESTMENT),
    ("casa de playa", Motivation.VACATION),
    ("casa de campo", Motivation.VACATION),
    ("para vacacionar", Motivation.VACATION),
    ("segunda vivienda", Motivation.VACATION),
    ("para veranear", Motivation.VACATION),
    ("uso vacacional", Motivation.VACATION),
)

_OBJECTION_KEYWORDS: tuple[tuple[str, ObjectionType], ...] = (
    ("muy caro", ObjectionType.PRECIO),
    ("carisimo", ObjectionType.PRECIO),
    ("no tengo presupuesto para", ObjectionType.PRECIO),
    ("se me va del presupuesto", ObjectionType.PRECIO),
    ("no me alcanza", ObjectionType.PRECIO),
    ("no me gusta la zona", ObjectionType.ZONA),
    ("esa zona no", ObjectionType.ZONA),
    ("muy lejos", ObjectionType.ZONA),
    ("zona insegura", ObjectionType.ZONA),
    ("no califico", ObjectionType.FINANCIAMIENTO),
    ("no me aprueban", ObjectionType.FINANCIAMIENTO),
    ("problema con el banco", ObjectionType.FINANCIAMIENTO),
    ("no tengo para la cuota inicial", ObjectionType.FINANCIAMIENTO),
    ("muy pequeño", ObjectionType.TAMANO),
    ("muy chico", ObjectionType.TAMANO),
    ("necesito mas espacio", ObjectionType.TAMANO),
    ("muy grande para lo que busco", ObjectionType.TAMANO),
    ("aun no es el momento", ObjectionType.TIEMPO),
    ("no tengo apuro", ObjectionType.TIEMPO),
    ("mas adelante", ObjectionType.TIEMPO),
    ("todavia lo estoy pensando", ObjectionType.TIEMPO),
)

_MUST_HAVE_MARKERS = (
    "indispensable que",
    "imprescindible que",
    "necesito que tenga",
    "necesita que tenga",
    "debe tener",
    "tiene que tener",
)

#: Optional currency marker ("$", "S/", "USD", "US$") immediately before an
#: amount — matched but not captured, so a range like "$100,000 y $150,000"
#: or "S/ 200,000" still resolves to a plain numeric amount/range.
_CURRENCY_PREFIX = r"(?:s/\.?|us\$|\$|usd)?\s*"

_RANGE_RE = re.compile(
    _CURRENCY_PREFIX
    + r"(?P<a>\d[\d.,]*)\s*(?P<au>k|mil)?\s*(?:-|a|y|hasta)\s*"
    + _CURRENCY_PREFIX
    + r"(?P<b>\d[\d.,]*)\s*(?P<bu>k|mil)?",
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(
    _CURRENCY_PREFIX + r"(?P<a>\d[\d.,]*)\s*(?P<au>k|mil)?", re.IGNORECASE
)

#: Words that mark a number as money talk even when the amount is small.
_BUDGET_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "presupuesto",
    "precio",
    "pagar",
    "invertir",
    "cuesta",
    "costar",
    "dolares",
    "soles",
    "usd",
    "$",
)
#: Below this, a bare number ("en 3 meses", "2 dormitorios") is almost
#: certainly not a property budget.
_MIN_PLAUSIBLE_BUDGET = 1000.0


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


def has_budget_signal(text: str) -> bool:
    """Routing guard for the turn orchestrator (`qualification_turn.py`):
    decides whether `extract_budget` should run at all. A bare small number
    ("en 3 meses", "2 dormitorios") is not money talk — without this guard the
    budget extractor would capture it and corrupt the profile."""
    amounts = _extract_budget_range(text)
    if amounts is None:
        return False
    if amounts[1] >= _MIN_PLAUSIBLE_BUDGET:
        return True
    normalized = _normalize(text)
    return any(keyword in normalized for keyword in _BUDGET_CONTEXT_KEYWORDS)


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
        cleaned = _dedupe_case_insensitive(item.strip(" .") for item in items if item.strip(" ."))
        if cleaned:
            return cleaned
    return None


def _dedupe_case_insensitive(items: Iterable[str]) -> tuple[str, ...]:
    """Order-preserving, case/whitespace-insensitive dedup: keeps the first
    casing seen for each distinct requirement (e.g. "cochera" and "Cochera"
    in the same message collapse to one entry)."""
    seen: dict[str, str] = {}
    for item in items:
        key = _normalize(item).strip()
        if key not in seen:
            seen[key] = item
    return tuple(seen.values())


async def extract_timeline(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> ExtractionResult:
    """US-205/US-222: purchase timeline — split from `must_haves` (US-222) so
    each can carry its own `PROFILE_DIMENSIONS` precedence (`timeline` is
    Nivel 2, `must_haves` is Nivel 1)."""
    timeline = _extract_timeline(_normalize(text))
    if timeline is None:
        return None

    await _assert_tenant(session, lead_id, organization_id)
    try:
        patch = ProfilePatch(timeline=timeline)
    except ProfileValidationError:
        return None  # unreachable: timeline is non-None here

    service = BuyerProfileCaptureService(session)
    await service.update_profile(lead_id, patch)
    return patch


async def extract_must_haves(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> ExtractionResult:
    """US-205/US-222: non-negotiable requirements — split from `timeline`
    (US-222) so each can carry its own `PROFILE_DIMENSIONS` precedence
    (`must_haves` is Nivel 1, `timeline` is Nivel 2)."""
    normalized = _normalize(text)
    must_haves = _extract_must_haves(text, normalized)
    if must_haves is None:
        return None

    await _assert_tenant(session, lead_id, organization_id)
    try:
        patch = ProfilePatch(must_haves=must_haves)
    except ProfileValidationError:
        return None  # unreachable: must_haves is non-None here

    service = BuyerProfileCaptureService(session)
    await service.update_profile(lead_id, patch)
    return patch


def _extract_financing(normalized_text: str) -> FinancingType | None:
    for keyword, financing_type in _FINANCING_KEYWORDS:
        if _normalize(keyword) in normalized_text:
            return financing_type
    return None


def _extract_decision_mode(normalized_text: str) -> DecisionMakerMode | None:
    for keyword, decision_mode in _DECISION_MODE_KEYWORDS:
        if _normalize(keyword) in normalized_text:
            return decision_mode
    return None


async def extract_financing_and_decision_mode(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> ExtractionResult:
    """US-208: financing type and/or decision-maker mode, both may be present
    in the same message and land in a single `ProfilePatch`."""
    normalized = _normalize(text)
    financing_type = _extract_financing(normalized)
    decision_maker_mode = _extract_decision_mode(normalized)
    if financing_type is None and decision_maker_mode is None:
        return None

    await _assert_tenant(session, lead_id, organization_id)
    try:
        patch = ProfilePatch(
            financing_type=financing_type, decision_maker_mode=decision_maker_mode
        )
    except ProfileValidationError:
        return None  # unreachable: both fields are None or non-empty here

    service = BuyerProfileCaptureService(session)
    await service.update_profile(lead_id, patch)
    return patch


#: Bedroom count requires its keyword right after the number — a bare "3"
#: is a timeline (or anything else), never a bedroom count.
_BEDROOMS_RE = re.compile(
    r"\b(\d{1,2}|un|una|uno|dos|tres|cuatro|cinco|seis)\s+"
    r"(?:dormitorios?|habitacion(?:es)?|cuartos?|dorms?|ambientes?)\b"
)

_WORD_NUMBERS = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
}


def _extract_bedroom_count(normalized_text: str) -> int | None:
    match = _BEDROOMS_RE.search(normalized_text)
    if match is None:
        return None
    raw = match.group(1)
    count = _WORD_NUMBERS.get(raw) or int(raw)
    return count if 1 <= count <= 15 else None


async def extract_bedrooms(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> ExtractionResult:
    """Bedroom count — eighth profile dimension (2026-07-19 E2E review)."""
    count = _extract_bedroom_count(_normalize(text))
    if count is None:
        return None

    await _assert_tenant(session, lead_id, organization_id)
    try:
        patch = ProfilePatch(bedrooms=count)
    except ProfileValidationError:
        return None

    service = BuyerProfileCaptureService(session)
    await service.update_profile(lead_id, patch)
    return patch


def _extract_motivation(normalized_text: str) -> Motivation | None:
    best_index: int | None = None
    best_motivation: Motivation | None = None
    for keyword, motivation in _MOTIVATION_KEYWORDS:
        index = normalized_text.find(_normalize(keyword))
        if index != -1 and (best_index is None or index < best_index):
            best_index = index
            best_motivation = motivation
    return best_motivation


async def extract_motivation(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> ExtractionResult:
    """US-219: closed-enum purchase-motivation classification (mudanza,
    inversion, vacacional, primera vivienda), keyword-first — mirrors
    `extract_property_type`."""
    motivation = _extract_motivation(_normalize(text))
    if motivation is None:
        return None

    await _assert_tenant(session, lead_id, organization_id)
    try:
        patch = ProfilePatch(motivation=motivation)
    except ProfileValidationError:
        return None  # unreachable: motivation is a plain enum, no shape validation

    service = BuyerProfileCaptureService(session)
    await service.update_profile(lead_id, patch)
    return patch


def _extract_objection_type(normalized_text: str) -> ObjectionType | None:
    for keyword, objection_type in _OBJECTION_KEYWORDS:
        if _normalize(keyword) in normalized_text:
            return objection_type
    return None


async def extract_objection(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
) -> ObjectionExtractionResult:
    """US-209: single best-match objection detection (closed-enum, keyword
    first, mirrors `extract_property_type`). Persists via
    `LeadScoringService.record_objection`, which also recomputes
    `Lead.lead_score`/`lead_classification` — not a `BuyerProfile` dimension,
    so `BuyerProfileCaptureService` is not involved here."""
    normalized = _normalize(text)
    objection_type = _extract_objection_type(normalized)
    if objection_type is None:
        return None

    await _assert_tenant(session, lead_id, organization_id)
    service = LeadScoringService(session)
    await service.record_objection(
        lead_id,
        organization_id=organization_id,
        objection_type=objection_type,
        raw_text=text,
    )
    return objection_type
