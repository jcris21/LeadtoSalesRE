## Why

`AI-106` in `Documents/Oficial/HU_Calificacion_Recomendacion.md` (lines 736-746) asks for a
Knowledge/RAG Service that answers objections and informational questions with content grounded in
an approved knowledge base, instead of only detecting and scoring the objection. Today
`qualification_flow.py::extract_objection` + `LeadScoringService.record_objection` detect and score
an objection deterministically but never generate a response. There is no RAG module, no document
vector store, and no `KnowledgeService` in the repo (distinct from the `property_embeddings`
pgvector store, which indexes properties, not knowledge).

`AI-106` formally depends on `AI-105` (Intent Router), which does not exist in this repo yet and is
out of scope here. The dependency-analysis table in the same document (line 1013) says the RAG
retrieval service itself can be prototyped in parallel with the Intent Router track; only the
wiring that decides *when* to invoke it (Objecion vs Q&A) needs the category the Intent Router
produces. This change builds exactly that standalone, independently testable piece.

## What Changes

- Add a new `app/modules/knowledge/` bounded-context module (`domain/`, `application/`,
  `infrastructure/`), mirroring the layout of `recommendation/` and `lead_qualification/`.
- Add `KnowledgeDocument` / `KnowledgeCategory` / `KnowledgeAnswer` domain models.
- Add a `knowledge_documents` table (own pgvector store, separate from `property_embeddings`):
  id, organization_id, title, content, category, embedding vector(1536), approved, created_at.
- Add `KnowledgeRepository` (find_similar filtered by organization_id + approved + optional
  category, add_document) reusing the existing `GeminiEmbeddingModel`/`build_embedding_model`
  seam from `app/modules/recommendation/infrastructure/embedding_model.py` - no duplicate
  embedding client.
- Add `KnowledgeService.answer(organization_id, query, category=None, top_k=3) -> KnowledgeAnswer`:
  embeds the query, retrieves top-K approved passages, and assembles the answer **extractively**
  (paraphrase/quote retrieved content only - never invents figures not present in the KB).
- Add Alembic migration `0020_knowledge_documents.py` (head is `0019_outbox_retry_backoff`),
  enabling pgvector + an HNSW index, mirroring migrations `0011`/`0013`.
- Add `tests/test_knowledge_service.py` covering retrieval scoping, grounding, and the empty-KB
  case, hermetic (SQLite, deterministic embedder, no network).

## Non-Goal: AI-105 wiring (explicit scope boundary)

This change does **not**:
- Wire `KnowledgeService` into `CoordinatorAgent.handle_message`.
- Invent an `IntentRouter`/`IntentRouterPort` or any classification step.
- Change `qualification_flow.py`, `lead_scoring.py`, or any Coordinator turn-handling code.

`KnowledgeService.answer(...)` is a clean, independently callable service. A future change, once
`AI-105` (Intent Router) exists and produces a category (`objecion` / `pregunta_informativa`),
wires the "when to call `KnowledgeService`" decision on top of it - exactly the same boundary
`2026-07-25-intent-router-ai-104` drew around consuming its own classification output ("no
downstream consumers of the classified category exist yet in this change").

## Capabilities

### New Capabilities
- `knowledge-rag`: retrieval-augmented, extractive answer assembly over an approved,
  organization-scoped knowledge base, consumable by any future caller (objection handling, Q&A)
  via `KnowledgeService.answer`.

### Modified Capabilities
(none)

## Impact

- New module: `app/modules/knowledge/` (domain, application, infrastructure).
- New migration: `alembic/versions/0020_knowledge_documents.py`.
- New table: `knowledge_documents`.
- No changes to `app/modules/conversation_ownership/`, `app/modules/lead_qualification/`, or
  `app/modules/recommendation/` (only imports the existing embedding seam, does not modify it).
- No new HTTP endpoints.
- Downstream: no consumer wires this service yet - that is explicitly future work (see Non-Goal).
