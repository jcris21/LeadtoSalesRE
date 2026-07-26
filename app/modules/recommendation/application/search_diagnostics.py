"""Zero-result search diagnostics (US-hallucination-fix, 2026-07-24 incident).

CW-DEMO-1784860599/MSG-0010: a lead asked for a property under a budget that
had zero matches in Supabase; the conversational brain (which never sees the
`properties` table) filled the vacuum by inventing two listings with fake
links. `RecommendationService` already has a real, empty-safe SQL filter
(`retrieval.py` -> `PropertyRepository.filter_candidates`), but it only runs
once, from the `ProfileCompleted` event — not on every mid-conversation
budget/zone update.

This module runs that same structured filter ad hoc, from the Coordinator's
conversational turn, and — when it comes back empty — tells apart *why*
(no property in the requested zone at all, vs. the zone has stock but none of
it fits the budget) so the LLM is handed a fact to narrate instead of a blank
page to improvise on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.modules.lead_qualification.domain.models import MoneyRange, PropertyType
from app.modules.recommendation.domain.models import Property

#: How far outside the requested budget a property still counts as "closer
#: price" worth mentioning to the lead (20% on each end).
PRICE_TOLERANCE = 0.20


class PropertyDiagnosticsLookup(Protocol):
    """The narrow read surface this module needs from a property store —
    satisfied structurally by `infrastructure.repository.PropertyRepository`."""

    async def filter_candidates(
        self,
        organization_id: uuid.UUID,
        *,
        budget: MoneyRange | None,
        zones: tuple[str, ...],
        property_type: PropertyType | None,
    ) -> list[Property]: ...

    async def count_available(
        self, organization_id: uuid.UUID, *, zones: tuple[str, ...] = ()
    ) -> int: ...

    async def count_near_price(
        self,
        organization_id: uuid.UUID,
        *,
        budget: MoneyRange,
        zones: tuple[str, ...] = (),
        tolerance: float = PRICE_TOLERANCE,
    ) -> int: ...


@dataclass(frozen=True)
class SearchDiagnosis:
    """What the structured filter found (or didn't) for the lead's current
    budget/zone criteria — the fact the conversational LLM must narrate
    instead of inventing its own explanation."""

    has_matches: bool
    zone_mismatch: bool
    price_mismatch: bool
    zones: tuple[str, ...] = ()
    budget: MoneyRange | None = None
    city_available_count: int = 0
    near_price_count: int = 0


async def diagnose(
    store: PropertyDiagnosticsLookup,
    *,
    organization_id: uuid.UUID,
    budget: MoneyRange | None,
    zones: tuple[str, ...],
    property_type: PropertyType | None,
) -> SearchDiagnosis | None:
    """Returns `None` when there is no budget and no zone yet — an ordinary
    qualification turn, nothing to ground. Otherwise runs the real hard-filter
    query and, on an empty result, isolates whether the requested zone has no
    stock at all (`zone_mismatch`) or has stock but none within budget
    (`price_mismatch`)."""
    if budget is None and not zones:
        return None

    matches = await store.filter_candidates(
        organization_id, budget=budget, zones=zones, property_type=property_type
    )
    if matches:
        return SearchDiagnosis(
            has_matches=True, zone_mismatch=False, price_mismatch=False, zones=zones, budget=budget
        )

    zone_available_count = await store.count_available(organization_id, zones=zones) if zones else None
    zone_mismatch = bool(zones) and zone_available_count == 0

    price_mismatch = False
    near_price_count = 0
    city_available_count = await store.count_available(organization_id)
    if not zone_mismatch and budget is not None:
        price_mismatch = True
        near_price_count = await store.count_near_price(organization_id, budget=budget, zones=zones)
        if near_price_count == 0 and zones:
            # Nothing near-price even inside the requested zone(s) — widen the
            # count to the whole city so the lead still gets a real number.
            near_price_count = await store.count_near_price(organization_id, budget=budget)

    return SearchDiagnosis(
        has_matches=False,
        zone_mismatch=zone_mismatch,
        price_mismatch=price_mismatch,
        zones=zones,
        budget=budget,
        city_available_count=city_available_count,
        near_price_count=near_price_count,
    )


def render_grounding_note(diagnosis: SearchDiagnosis) -> str:
    """A system-context instruction for the conversational LLM: states the
    real fact this turn (matches / zone mismatch / price mismatch) and what to
    do about it, so the model narrates a real number instead of a fabricated
    listing. Never includes a property link — those stay the exclusive
    responsibility of the deterministic `RecommendationService` composer."""
    if diagnosis.has_matches:
        return (
            "Contexto interno (no lo repitas textual): SÍ hay propiedades disponibles "
            "que calzan con la zona y presupuesto actuales del lead. Dile que hay "
            "opciones que le pueden interesar y que en breve tendrá el Top-3; NO "
            "menciones precios, direcciones ni enlaces específicos en este mensaje — "
            "esos los entrega únicamente el motor de recomendación."
        )

    if diagnosis.zone_mismatch:
        zonas = ", ".join(diagnosis.zones) or "la zona indicada"
        return (
            f"Contexto interno (no lo repitas textual): no hay propiedades disponibles "
            f"en {zonas}. Explícale al lead ese motivo exacto sin inventar direcciones "
            f"ni proyectos. Cuéntale que en la ciudad hay "
            f"{diagnosis.city_available_count} proyectos disponibles en total, invítalo "
            f"a indicar otra zona de su interés, y pregúntale si de todos modos quiere "
            f"que le busques el Top-3 disponible en la ciudad."
        )

    if diagnosis.price_mismatch:
        rango = (
            f"USD {diagnosis.budget.minimum:,.0f} a {diagnosis.budget.maximum:,.0f}"
            if diagnosis.budget is not None
            else "el rango indicado"
        )
        return (
            f"Contexto interno (no lo repitas textual): no hay propiedades disponibles "
            f"dentro del presupuesto {rango}. Explícale al lead ese motivo exacto sin "
            f"inventar precios ni proyectos. Cuéntale que hay "
            f"{diagnosis.near_price_count} proyectos disponibles con precio más cercano "
            f"y/o criterios más flexibles, y pregúntale si quiere que igual le busques "
            f"el Top-3 con esas opciones."
        )

    return (
        "Contexto interno (no lo repitas textual): no hay propiedades que calcen "
        "exactamente con los criterios actuales del lead. Explícaselo sin inventar "
        f"datos; cuéntale que hay {diagnosis.city_available_count} proyectos "
        "disponibles en la ciudad y pregúntale si quiere que le busques el Top-3 "
        "disponible."
    )
