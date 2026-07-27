## 1. Domain

- [x] 1.1 Create `app/modules/knowledge/domain/models.py` with `KnowledgeCategory` (StrEnum),
      `KnowledgeDocument` (dataclass), `KnowledgeAnswer` (frozen dataclass/ValueObject).
- [x] 1.2 `app/modules/knowledge/__init__.py`, `domain/__init__.py`.

## 2. Infrastructure

- [x] 2.1 Create `app/modules/knowledge/infrastructure/db_models.py` with `KnowledgeDocumentORM`
      (portable JSON embedding column, mirrors `PropertyEmbeddingORM`).
- [x] 2.2 Create `app/modules/knowledge/infrastructure/repository.py` with `KnowledgeRepository`:
      `add_document`, `find_similar` (dialect-gated: raw SQL pgvector `<->` on Postgres, Python
      cosine ranking on SQLite).
- [x] 2.3 `infrastructure/__init__.py`.
- [x] 2.4 Create `alembic/versions/0020_knowledge_documents.py` (down_revision `0019`): creates
      `knowledge_documents`, enables pgvector, adds HNSW index.

## 3. Application

- [x] 3.1 Create `app/modules/knowledge/application/knowledge_service.py` with
      `AnswerPhraserPort` (Protocol seam, unused by default), `_assemble_answer` (extractive),
      and `KnowledgeService.answer(organization_id, query, category=None, top_k=3)`.
- [x] 3.2 `application/__init__.py`.

## 4. Tests

- [x] 4.1 Retrieval returns only `approved=true` documents.
- [x] 4.2 Retrieval is scoped by `organization_id` (cross-tenant isolation).
- [x] 4.3 `answer_text` never contains content absent from the retrieved passages (grounding).
- [x] 4.4 Category filter narrows results to the matching category.
- [x] 4.5 Empty KB / no match returns `found=False` with a clear message, no exception.
- [x] 4.6 `add_document` + `answer` round-trip works fully in SQLite with a deterministic embedder,
      no network call, no `gemini_api_key`.

## 5. Verification

- [x] 5.1 Run `uv run pytest tests/test_knowledge_service.py -v` (or repo's pytest invocation) and
      confirm all tests pass.
- [x] 5.2 Mark all tasks above done.
