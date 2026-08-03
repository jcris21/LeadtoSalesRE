"""Knowledge/RAG Service (AI-106): retrieval-augmented, extractive answer assembly over an
approved, organization-scoped knowledge base.

Scope boundary (see openspec/changes/knowledge-rag-service-ai-106/proposal.md): this module is
standalone and independently callable. It is NOT wired into `CoordinatorAgent.handle_message`, and
no `IntentRouter`/`AI-105` classification step exists here or is invented by this change. A future
change decides *when* to call `KnowledgeService.answer` (objection vs Q&A); this module only
answers once called.

Grounding guarantee (Regla 2/QA-6, "sin cifras no verificadas"): `_assemble_answer` is purely
extractive - it concatenates/trims retrieved passage `content` with a fixed connective phrase and
never calls a free-form text generator, so `answer_text` cannot contain a figure or fact absent
from the retrieved, approved passages. `AnswerPhraserPort` is a `Protocol` seam (same shape as
`ExplanationGenerator`/`SignalPhraser` in `recommendation/application/explanation_generator.py`)
left for a future LLM-backed rephraser; no implementation ships here.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.domain.models import KnowledgeAnswer, KnowledgeCategory, KnowledgeDocument
from app.modules.knowledge.infrastructure.repository import KnowledgeRepository

_NO_INFO_TEMPLATE = (
    "No encontre informacion aprobada sobre eso en la base de conocimiento todavia."
)
_CONNECTIVE = " "


class QueryEmbedder(Protocol):
    """Turns arbitrary text (a query or a document's content) into an embedding vector. Same
    async shape as `recommendation.application.property_ingestion.EmbeddingModel`, generalized
    from `Property` to plain `str` since knowledge passages are not properties."""

    model_version: str

    async def embed_text(self, text: str) -> tuple[float, ...]: ...


class AnswerPhraserPort(Protocol):
    """Seam for a future LLM-backed rephraser (design.md: not implemented in this change). Any
    implementation MUST still only draw from `passages` - grounding is not optional."""

    async def phrase(self, query: str, passages: list[str]) -> str: ...


def _assemble_answer(passages: list[str]) -> str:
    """Extractive assembly (design.md Decisions): trims and joins passage content with a fixed
    connective - never introduces text absent from `passages`."""
    trimmed = [p.strip() for p in passages if p.strip()]
    return _CONNECTIVE.join(trimmed)


class KnowledgeService:
    """AI-106: embeds a query, retrieves approved organization-scoped passages, and assembles a
    grounded answer. Not wired into any turn/Coordinator (see module docstring)."""

    def __init__(self, session: AsyncSession, embedder: QueryEmbedder) -> None:
        self._repo = KnowledgeRepository(session)
        self._embedder = embedder

    async def answer(
        self,
        organization_id: uuid.UUID,
        query: str,
        *,
        category: KnowledgeCategory | None = None,
        top_k: int = 3,
    ) -> KnowledgeAnswer:
        query_vector = await self._embedder.embed_text(query)
        passages = await self._repo.find_similar(
            organization_id, query_vector=query_vector, category=category, top_k=top_k
        )
        if not passages:
            return KnowledgeAnswer(
                answer_text=_NO_INFO_TEMPLATE,
                source_document_ids=(),
                category=category,
                found=False,
            )
        answer_text = _assemble_answer([doc.content for doc in passages])
        return KnowledgeAnswer(
            answer_text=answer_text,
            source_document_ids=tuple(doc.id for doc in passages),
            category=category,
            found=True,
        )

    async def add_document(
        self, document: KnowledgeDocument, *, embedding: tuple[float, ...] | None = None
    ) -> None:
        """Seeds/updates a document, embedding its `content` via the configured embedder unless
        an explicit `embedding` is supplied (tests). No dedup/idempotency (design.md D3)."""
        vector = embedding if embedding is not None else await self._embedder.embed_text(
            document.content
        )
        await self._repo.add_document(document, embedding=vector)


class HashTextEmbedder:
    """Deterministic default (design.md Decisions): hashes arbitrary text into a fixed-length
    float vector. Keeps `KnowledgeService` fully testable without an API key or network call -
    same rationale/shape as `recommendation.application.property_ingestion.HashEmbeddingModel`,
    generalized from `Property` to plain `str`."""

    model_version = "hash-v1"
    vector_size = 16

    async def embed_text(self, text: str) -> tuple[float, ...]:
        digest = hashlib.sha256(text.encode()).digest()
        return tuple(digest[i % len(digest)] / 255.0 for i in range(self.vector_size))


class _GeminiQueryEmbedderAdapter:
    """Adapts `recommendation.infrastructure.embedding_model.GeminiEmbeddingModel` (which embeds
    arbitrary text via `embed_text`) to the `QueryEmbedder` protocol - no duplicate HTTP client,
    no duplicate retry/backoff logic."""

    model_version: str

    def __init__(self, gemini_model) -> None:
        self._model = gemini_model
        self.model_version = gemini_model.model_version

    async def embed_text(self, text: str) -> tuple[float, ...]:
        return await self._model.embed_text(text, context="knowledge query")


def build_default_query_embedder(api_key: str | None) -> QueryEmbedder:
    """Config-driven embedder selection, mirroring
    `recommendation.infrastructure.embedding_model.build_embedding_model` (design.md Decisions):
    with `gemini_api_key` set, reuses the real `GeminiEmbeddingModel`; without it, the
    deterministic `HashTextEmbedder` so tests and keyless environments make no network call."""
    if api_key:
        from app.modules.recommendation.infrastructure.embedding_model import (
            GeminiEmbeddingModel,
        )

        return _GeminiQueryEmbedderAdapter(GeminiEmbeddingModel(api_key))
    return HashTextEmbedder()
