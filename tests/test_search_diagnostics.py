"""US-hallucination-fix (2026-07-24, CW-DEMO-1784860599/MSG-0010): a lead
asked for a property under a budget with zero Supabase matches and the
conversational brain invented two listings with fake links. `diagnose()` runs
the real structured filter and tells apart a zone mismatch (no stock in the
requested zone at all) from a price mismatch (the zone has stock, just none
of it in budget) so the LLM narrates a real fact instead of improvising."""

from __future__ import annotations

import uuid

import pytest

from app.modules.lead_qualification.domain.models import MoneyRange, PropertyType
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.application.search_diagnostics import (
    diagnose,
    render_grounding_note,
)
from app.modules.recommendation.domain.models import Property
from app.modules.recommendation.infrastructure.repository import PropertyRepository
from app.shared.domain.base import new_id, utcnow


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded_org(session_factory, org_id):
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org Test", status="active", created_at=utcnow()))
        await session.commit()
    return org_id


def _property(org_id, *, price=100_000.0, zone="Miraflores", estado="disponible"):
    return Property(
        organization_id=org_id,
        external_id=str(uuid.uuid4()),
        price=price,
        zone=zone,
        property_type=PropertyType.APARTMENT,
        estado=estado,
    )


async def _seed(session_factory, properties):
    async with session_factory() as session:
        repo = PropertyRepository(session)
        for p in properties:
            await repo.upsert(p)
        await session.commit()


async def test_diagnose_returns_none_without_budget_or_zone(session_factory, seeded_org):
    async with session_factory() as session:
        diagnosis = await diagnose(
            PropertyRepository(session),
            organization_id=seeded_org,
            budget=None,
            zones=(),
            property_type=None,
        )
    assert diagnosis is None


async def test_diagnose_has_matches_when_filter_finds_stock(session_factory, seeded_org):
    await _seed(session_factory, [_property(seeded_org, price=100_000.0, zone="Miraflores")])

    async with session_factory() as session:
        diagnosis = await diagnose(
            PropertyRepository(session),
            organization_id=seeded_org,
            budget=MoneyRange(minimum=50_000.0, maximum=150_000.0),
            zones=("Miraflores",),
            property_type=None,
        )
    assert diagnosis.has_matches is True
    assert diagnosis.zone_mismatch is False
    assert diagnosis.price_mismatch is False


async def test_diagnose_flags_zone_mismatch_when_zone_has_no_stock(session_factory, seeded_org):
    await _seed(session_factory, [_property(seeded_org, price=100_000.0, zone="Surco")])

    async with session_factory() as session:
        diagnosis = await diagnose(
            PropertyRepository(session),
            organization_id=seeded_org,
            budget=MoneyRange(minimum=50_000.0, maximum=150_000.0),
            zones=("Miraflores",),
            property_type=None,
        )
    assert diagnosis.has_matches is False
    assert diagnosis.zone_mismatch is True
    assert diagnosis.price_mismatch is False
    assert diagnosis.city_available_count == 1  # the Surco property, citywide


async def test_diagnose_flags_price_mismatch_when_zone_has_stock_out_of_budget(
    session_factory, seeded_org
):
    # Reproduces the incident: the requested zone has real, available stock,
    # but all of it prices above the lead's stated budget of 150,000.
    await _seed(
        session_factory,
        [
            _property(seeded_org, price=180_000.0, zone="Miraflores"),
            _property(seeded_org, price=190_000.0, zone="Miraflores"),
        ],
    )

    async with session_factory() as session:
        diagnosis = await diagnose(
            PropertyRepository(session),
            organization_id=seeded_org,
            budget=MoneyRange(minimum=100_000.0, maximum=150_000.0),
            zones=("Miraflores",),
            property_type=None,
        )
    assert diagnosis.has_matches is False
    assert diagnosis.zone_mismatch is False
    assert diagnosis.price_mismatch is True
    # 180,000 is within the +20% tolerance band (up to 180,000); 190,000 is not.
    assert diagnosis.near_price_count == 1


async def test_diagnose_ignores_sold_out_stock_for_availability_counts(session_factory, seeded_org):
    await _seed(
        session_factory,
        [_property(seeded_org, price=100_000.0, zone="Surco", estado="vendido")],
    )

    async with session_factory() as session:
        diagnosis = await diagnose(
            PropertyRepository(session),
            organization_id=seeded_org,
            budget=MoneyRange(minimum=50_000.0, maximum=150_000.0),
            zones=("Miraflores",),
            property_type=None,
        )
    assert diagnosis.zone_mismatch is True
    assert diagnosis.city_available_count == 0  # sold-out stock never counts as available


def test_render_grounding_note_zone_mismatch_invites_another_zone_and_top3():
    from app.modules.recommendation.application.search_diagnostics import SearchDiagnosis

    diagnosis = SearchDiagnosis(
        has_matches=False,
        zone_mismatch=True,
        price_mismatch=False,
        zones=("Miraflores",),
        budget=MoneyRange(minimum=100_000.0, maximum=150_000.0),
        city_available_count=7,
    )
    note = render_grounding_note(diagnosis)
    assert "Miraflores" in note
    assert "7" in note
    assert "Top-3" in note


def test_render_grounding_note_price_mismatch_offers_near_price_count():
    from app.modules.recommendation.application.search_diagnostics import SearchDiagnosis

    diagnosis = SearchDiagnosis(
        has_matches=False,
        zone_mismatch=False,
        price_mismatch=True,
        zones=("Miraflores",),
        budget=MoneyRange(minimum=100_000.0, maximum=150_000.0),
        near_price_count=3,
    )
    note = render_grounding_note(diagnosis)
    assert "150,000" in note or "150000" in note.replace(",", "")
    assert "3" in note
    assert "Top-3" in note
