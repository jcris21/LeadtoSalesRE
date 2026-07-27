"""Repository translating between `KnowledgeDocument` and its ORM row, and the pgvector
similarity search behind `KnowledgeService.answer` (AI-106).

Dialect-gated persistence/query, same pattern as
`recommendation.infrastructure.repository.PropertyRepository`: on Postgres the `embedding` column
is `vector(1536)` and bound via raw SQL with an explicit `::vector` cast (the ORM's generic JSON
type cannot bind a pgvector column); on SQLite (tests) the ORM's portable JSON column is used
directly and cosine distance is computed in Python. Unlike `PropertyRepository.semantic_search`
(which returns `None` on non-Postgres so the *caller* falls back to a separate in-memory ranking
component), this repository resolves the fallback itself and always returns an ordered list - this
module has no existing hybrid-retrieval component to reuse for that split, and the KB corpus is
expected to be small enough that an in-process Python sort is a fine first cut.
"""

from __future__ import annotations

import math
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.domain.models import KnowledgeCategory, KnowledgeDocument
from app.modules.knowledge.infrastructure.db_models import KnowledgeDocumentORM


def _cosine_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """1 - cosine similarity, ascending order = most similar first - matches pgvector's `<->`
    ordering direction for unit-normalized vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    similarity = dot / (norm_a * norm_b)
    return 1.0 - similarity


class KnowledgeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add_document(
        self, document: KnowledgeDocument, *, embedding: tuple[float, ...]
    ) -> None:
        """Persists a `KnowledgeDocument` plus its embedding. Re-embeds/overwrites on every call
        for a given `document.id` - acceptable at authoring/seeding scale (design.md D3)."""
        if self._session.bind.dialect.name == "postgresql":
            vector_literal = "[" + ",".join(f"{v:.10f}" for v in embedding) + "]"
            await self._session.execute(
                text(
                    "INSERT INTO knowledge_documents "
                    "(id, organization_id, title, content, category, embedding, approved, "
                    "created_at) "
                    "VALUES (:id, :organization_id, :title, :content, :category, "
                    "CAST(:embedding AS vector), :approved, :created_at) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "title = EXCLUDED.title, content = EXCLUDED.content, "
                    "category = EXCLUDED.category, embedding = EXCLUDED.embedding, "
                    "approved = EXCLUDED.approved"
                ),
                {
                    "id": str(document.id),
                    "organization_id": str(document.organization_id),
                    "title": document.title,
                    "content": document.content,
                    "category": document.category.value,
                    "embedding": vector_literal,
                    "approved": document.approved,
                    "created_at": document.created_at,
                },
            )
            return
        row = await self._session.get(KnowledgeDocumentORM, document.id)
        if row is None:
            row = KnowledgeDocumentORM(id=document.id)
            self._session.add(row)
        row.organization_id = document.organization_id
        row.title = document.title
        row.content = document.content
        row.category = document.category.value
        row.embedding = list(embedding)
        row.approved = document.approved
        row.created_at = document.created_at

    async def find_similar(
        self,
        organization_id: uuid.UUID,
        *,
        query_vector: tuple[float, ...],
        category: KnowledgeCategory | None = None,
        top_k: int = 3,
    ) -> list[KnowledgeDocument]:
        """Approved, organization-scoped, optionally category-filtered top-K passages ranked by
        similarity to `query_vector`. Never raises on an empty result - returns `[]`."""
        if self._session.bind.dialect.name == "postgresql":
            return await self._find_similar_postgres(
                organization_id, query_vector=query_vector, category=category, top_k=top_k
            )
        return await self._find_similar_python(
            organization_id, query_vector=query_vector, category=category, top_k=top_k
        )

    async def _find_similar_postgres(
        self,
        organization_id: uuid.UUID,
        *,
        query_vector: tuple[float, ...],
        category: KnowledgeCategory | None,
        top_k: int,
    ) -> list[KnowledgeDocument]:
        vector_literal = "[" + ",".join(f"{v:.10f}" for v in query_vector) + "]"
        category_clause = " AND category = :category" if category is not None else ""
        params: dict[str, object] = {
            "organization_id": str(organization_id),
            "query_vector": vector_literal,
            "top_k": top_k,
        }
        if category is not None:
            params["category"] = category.value
        result = await self._session.execute(
            text(
                "SELECT id, organization_id, title, content, category, approved, created_at "
                "FROM knowledge_documents "
                "WHERE organization_id = :organization_id AND approved = true"
                + category_clause
                + " ORDER BY embedding <-> CAST(:query_vector AS vector) LIMIT :top_k"
            ),
            params,
        )
        return [self._row_to_domain(row) for row in result.mappings().all()]

    async def _find_similar_python(
        self,
        organization_id: uuid.UUID,
        *,
        query_vector: tuple[float, ...],
        category: KnowledgeCategory | None,
        top_k: int,
    ) -> list[KnowledgeDocument]:
        query = select(KnowledgeDocumentORM).where(
            KnowledgeDocumentORM.organization_id == organization_id,
            KnowledgeDocumentORM.approved.is_(True),
        )
        if category is not None:
            query = query.where(KnowledgeDocumentORM.category == category.value)
        result = await self._session.execute(query)
        rows = result.scalars().all()
        ranked = sorted(
            rows, key=lambda row: _cosine_distance(query_vector, tuple(row.embedding))
        )
        return [self._to_domain(row) for row in ranked[:top_k]]

    @staticmethod
    def _to_domain(row: KnowledgeDocumentORM) -> KnowledgeDocument:
        return KnowledgeDocument(
            id=row.id,
            organization_id=row.organization_id,
            title=row.title,
            content=row.content,
            category=KnowledgeCategory(row.category),
            approved=row.approved,
            created_at=row.created_at,
        )

    @staticmethod
    def _row_to_domain(row) -> KnowledgeDocument:
        return KnowledgeDocument(
            id=uuid.UUID(str(row["id"])),
            organization_id=uuid.UUID(str(row["organization_id"])),
            title=row["title"],
            content=row["content"],
            category=KnowledgeCategory(row["category"]),
            approved=row["approved"],
            created_at=row["created_at"],
        )
