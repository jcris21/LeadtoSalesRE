"""AI-106: KnowledgeService retrieval + grounding tests. Hermetic - SQLite, deterministic
HashTextEmbedder, no network call, no gemini_api_key required (mirrors
test_property_ingestion.py's fixture style)."""

from __future__ import annotations


import pytest

from app.modules.knowledge.application.knowledge_service import (
    HashTextEmbedder,
    KnowledgeService,
)
from app.modules.knowledge.domain.models import KnowledgeCategory, KnowledgeDocument
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow


def _document(
    organization_id,
    *,
    doc_id=None,
    title="Doc",
    content="Contenido de prueba.",
    category=KnowledgeCategory.GENERAL,
    approved=True,
):
    return KnowledgeDocument(
        id=doc_id or new_id(),
        organization_id=organization_id,
        title=title,
        content=content,
        category=category,
        approved=approved,
        created_at=utcnow(),
    )


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
def other_org_id():
    return new_id()


@pytest.fixture
async def seeded_orgs(session_factory, org_id, other_org_id):
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org A", status="active", created_at=utcnow()))
        session.add(
            OrganizationORM(id=other_org_id, name="Org B", status="active", created_at=utcnow())
        )
        await session.commit()
    return org_id, other_org_id


async def test_answer_returns_grounded_passage_for_approved_document(
    session_factory, seeded_orgs
):
    org_id, _ = seeded_orgs
    doc = _document(org_id, content="La zona tiene alta plusvalia historica segun registros.")

    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        await service.add_document(doc)
        await session.commit()

    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        result = await service.answer(org_id, "que tal la plusvalia de la zona?")

    assert result.found is True
    assert doc.id in result.source_document_ids
    assert doc.content.strip() in result.answer_text


async def test_answer_never_contains_content_absent_from_passages(session_factory, seeded_orgs):
    org_id, _ = seeded_orgs
    doc = _document(org_id, content="El financiamiento requiere cuota inicial del 10 por ciento.")

    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        await service.add_document(doc)
        await session.commit()
    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        result = await service.answer(org_id, "cuanto necesito de inicial?")

    answer_words = set(result.answer_text.split())
    source_words = set(doc.content.split())
    assert answer_words <= source_words


async def test_cross_tenant_document_is_never_retrieved(session_factory, seeded_orgs):
    org_id, other_org_id = seeded_orgs
    other_doc = _document(other_org_id, content="Informacion exclusiva de la otra organizacion.")

    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        await service.add_document(other_doc)
        await session.commit()
    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        result = await service.answer(org_id, "informacion exclusiva")

    assert result.found is False
    assert result.source_document_ids == ()


async def test_unapproved_document_is_never_retrieved(session_factory, seeded_orgs):
    org_id, _ = seeded_orgs
    doc = _document(org_id, content="Borrador pendiente de revision.", approved=False)

    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        await service.add_document(doc)
        await session.commit()
    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        result = await service.answer(org_id, "borrador")

    assert result.found is False


async def test_category_filter_narrows_retrieval(session_factory, seeded_orgs):
    org_id, _ = seeded_orgs
    precio_doc = _document(
        org_id, content="El precio incluye acabados premium.", category=KnowledgeCategory.PRECIO
    )
    zona_doc = _document(
        org_id, content="La zona es residencial y tranquila.", category=KnowledgeCategory.ZONA
    )

    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        await service.add_document(precio_doc)
        await service.add_document(zona_doc)
        await session.commit()
    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        result = await service.answer(
            org_id, "cuentame sobre el precio", category=KnowledgeCategory.PRECIO
        )

    assert result.found is True
    assert result.source_document_ids == (precio_doc.id,)
    assert zona_doc.id not in result.source_document_ids


async def test_empty_knowledge_base_returns_not_found_without_raising(
    session_factory, seeded_orgs
):
    org_id, _ = seeded_orgs

    async with session_factory() as session:
        service = KnowledgeService(session, HashTextEmbedder())
        result = await service.answer(org_id, "cualquier pregunta")

    assert result.found is False
    assert result.source_document_ids == ()
    assert result.answer_text
