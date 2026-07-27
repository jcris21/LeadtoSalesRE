"""Domain model of the Knowledge/RAG bounded context (AI-106).

`KnowledgeDocument` is an approved-or-not passage of curated content, scoped to an
organization and tagged with a `KnowledgeCategory`. `KnowledgeAnswer` is the result of
`KnowledgeService.answer` (application layer): grounded, extractive text plus the ids of the
passages it was built from - never free-form LLM prose, so it can never contain a figure absent
from the retrieved, approved content (Regla 2/QA-6, "sin cifras no verificadas").

Distinct from `app.modules.recommendation`'s `property_embeddings` store, which indexes
properties, not knowledge.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.shared.domain.base import utcnow


class KnowledgeCategory(StrEnum):
    """Closed set of knowledge topics (AI-106 ticket). Deliberately not a reuse of
    `lead_qualification.domain.models.ObjectionType`: that enum has `tamano`/`tiempo` (no KB
    counterpart here) and lacks `plusvalia`/`general`."""

    PRECIO = "precio"
    ZONA = "zona"
    PLUSVALIA = "plusvalia"
    FINANCIAMIENTO = "financiamiento"
    GENERAL = "general"


@dataclass(frozen=True)
class KnowledgeDocument:
    """One approved-or-pending passage of curated knowledge-base content."""

    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    content: str
    category: KnowledgeCategory
    approved: bool = False
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class KnowledgeAnswer:
    """Result of `KnowledgeService.answer`. `found=False` is an explicit "no information found"
    signal - callers must not infer emptiness from `answer_text` alone."""

    answer_text: str
    source_document_ids: tuple[uuid.UUID, ...]
    category: KnowledgeCategory | None
    found: bool
