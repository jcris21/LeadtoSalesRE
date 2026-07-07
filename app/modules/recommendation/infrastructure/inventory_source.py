"""Inventory adapter for the Property Ingestion Pipeline (Architecture.md
§6.3). No real inventory integration exists anywhere in this codebase yet, so
`MockInventorySource` yields a small deterministic synthetic catalog — enough
for the pipeline (and downstream Structured Filter / Semantic Retrieval /
Ranking tests) to exercise realistic fixtures. A real HTTP-backed source
later implements the same `fetch()` shape without touching the pipeline.
"""

from __future__ import annotations

import uuid

from app.modules.lead_qualification.domain.models import PropertyType
from app.modules.recommendation.domain.models import Property
from app.shared.domain.base import utcnow

#: Fixed namespace so `uuid.uuid5(_NAMESPACE, f"{org}:{external_id}")` is
#: stable across fetches — the mock's properties keep the same local id every
#: ingestion run, matching how a real inventory source's external_id would.
_NAMESPACE = uuid.UUID("7c8f3e10-3b0a-4b8e-9f0d-6a2c1e5d4b3a")

#: (external_id, price, zone, property_type, features, description)
_CATALOG: tuple[tuple[str, float, str, PropertyType, tuple[str, ...], str], ...] = (
    (
        "INV-001",
        135000.0,
        "Palermo",
        PropertyType.APARTMENT,
        ("balcony", "pet_friendly", "elevator"),
        "Bright 2BR apartment two blocks from the park, recently renovated kitchen.",
    ),
    (
        "INV-002",
        98000.0,
        "Palermo",
        PropertyType.APARTMENT,
        ("pet_friendly",),
        "Cozy studio, ideal for a single professional, close to public transit.",
    ),
    (
        "INV-003",
        320000.0,
        "Recoleta",
        PropertyType.HOUSE,
        ("garden", "garage", "pool"),
        "Spacious family house with private garden and two-car garage.",
    ),
    (
        "INV-004",
        275000.0,
        "Recoleta",
        PropertyType.HOUSE,
        ("garage", "fireplace"),
        "Classic three-bedroom house near the cathedral, recently painted.",
    ),
    (
        "INV-005",
        410000.0,
        "Belgrano",
        PropertyType.APARTMENT,
        ("balcony", "gym", "concierge"),
        "Modern high-rise apartment with river view and building amenities.",
    ),
    (
        "INV-006",
        150000.0,
        "Belgrano",
        PropertyType.APARTMENT,
        ("elevator",),
        "Quiet 1BR apartment on a tree-lined street, natural light all day.",
    ),
    (
        "INV-007",
        60000.0,
        "Villa Crespo",
        PropertyType.LAND,
        (),
        "Flat vacant lot zoned for residential construction.",
    ),
    (
        "INV-008",
        890000.0,
        "Belgrano",
        PropertyType.COMMERCIAL,
        ("storefront", "parking"),
        "Corner commercial space with street frontage, high foot traffic.",
    ),
    (
        "INV-009",
        210000.0,
        "Villa Crespo",
        PropertyType.APARTMENT,
        ("balcony", "pet_friendly"),
        "3BR apartment near the design district, open floor plan.",
    ),
    (
        "INV-010",
        175000.0,
        "Palermo",
        PropertyType.HOUSE,
        ("garden",),
        "Small house with a private backyard, walking distance to cafes.",
    ),
)


class MockInventorySource:
    """Synthetic stand-in for the (not-yet-built) real inventory adapter.
    Returns the same catalog for every organization, with the property's
    local id derived deterministically from `(organization_id, external_id)`
    so repeated fetches map onto the same local row (§6.3's "mirrored
    locally")."""

    async def fetch(self, organization_id: uuid.UUID) -> list[Property]:
        now = utcnow()
        return [
            Property(
                id=uuid.uuid5(_NAMESPACE, f"{organization_id}:{external_id}"),
                organization_id=organization_id,
                external_id=external_id,
                price=price,
                zone=zone,
                property_type=property_type,
                features=features,
                description=description,
                updated_at=now,
            )
            for external_id, price, zone, property_type, features, description in _CATALOG
        ]
