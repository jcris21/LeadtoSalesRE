## Original

#### AI-106 [NUEVA] - Knowledge/RAG Service unificado (Objection Handler + Q&A informativo)

Como AI Agent quiero responder objeciones (precio, zona, plusvalia, financiamiento) y preguntas
informativas del lead con contenido fundamentado en una base de conocimiento aprobada, en vez de
solo detectar y puntuar la objecion sin responderla.
Feature: Respuesta fundamentada a objeciones y preguntas
Scenario: Lead pregunta por plusvalia de la zona
  Given AI-105 clasifica el mensaje como Objecion o Pregunta informativa
  When KnowledgeService.answer recupera pasajes relevantes de la KB aprobada (RAG)
  Then la respuesta se redacta solo con esos pasajes (sin cifras no verificadas - Regla 2/QA-6)
  And se reutiliza la misma infraestructura de retrieval para ambos intents (Objecion y Q&A)
Alineacion: (a) Transversal a Discovery/Recommendation (Objecion) y a cualquier estado (Q&A).
(b) Capa agentic: no existe hoy. Lo unico implementado es la deteccion/puntuacion determinista sin
respuesta generada: qualification_flow.py::extract_objection + LeadScoringService.record_objection.
No hay modulo de RAG, vector store de documentos ni ObjectionHandler/KnowledgeService en el repo
(distinto del pgvector de property_embeddings que indexa propiedades, no conocimiento). (c) Tabla
nueva a definir (knowledge_documents + embeddings), fuera de property_embeddings. (d) [GAP] No
implementado. Depende de AI-105 para saber cuando invocarse.

## Enhanced

### Functionality description

Build a standalone KnowledgeService that retrieves approved knowledge-base passages via pgvector
similarity search and assembles a grounded answer from them - usable by objection handling
(precio/zona/plusvalia/financiamiento) and by informational Q&A once a caller decides to invoke it.

Scope boundary (explicit non-goal): AI-106 formally depends on AI-105 (Intent Router), which is
out of scope here and does not exist in this repo yet (only qualification_flow.py::extract_objection
plus LeadScoringService.record_objection - deterministic detection/scoring, no answer generation).
This change does NOT wire KnowledgeService into CoordinatorAgent.handle_message, and does not invent
an Intent Router. KnowledgeService.answer(...) is built and tested as an independently callable
service; a future AI-105-based change wires the "when to invoke" decision (Objecion vs Q&A) on top of
it.
This mirrors how openspec/changes/archive/2026-07-25-intent-router-ai-104 scoped IntentRouterPort
to classification only, without consuming the category anywhere yet.

### Fields / data model

New table knowledge_documents (own store, distinct from property_embeddings which indexes
properties, not knowledge):
- id: uuid (PK)
- organization_id: uuid (FK organizations.id, ondelete CASCADE, indexed - tenant isolation)
- title: str
- content: text
- category: str - one of precio, zona, plusvalia, financiamiento, general (closed enum,
  mirrors ObjectionType StrEnum pattern in lead_qualification/domain/models.py, but scoped
  to this module - plusvalia/general have no ObjectionType counterpart)
- embedding: vector(1536) on Postgres / portable JSON column on SQLite tests - same dual-typing
  convention as PropertyEmbeddingORM.vector
- approved: bool (default False - unapproved documents are never retrievable)
- created_at: datetime

### Domain objects

- KnowledgeDocument (dataclass): id, organization_id, title, content, category
  (KnowledgeCategory enum), approved, created_at.
- KnowledgeCategory(StrEnum): PRECIO, ZONA, PLUSVALIA, FINANCIAMIENTO, GENERAL.
- KnowledgeAnswer (frozen dataclass / ValueObject): answer_text, source_document_ids (tuple of
  uuid), category (KnowledgeCategory or None), found (bool - explicit "no info found" signal
  instead of an empty string, so callers don't have to infer emptiness).

### Service surface

No new HTTP endpoint - internal service, same posture as RecommendationService before its own
wiring. KnowledgeService.answer(organization_id, query, category=None, top_k=3) -> KnowledgeAnswer:
1. Embeds query via the existing embedding seam
   (app/modules/recommendation/infrastructure/embedding_model.py -
   GeminiEmbeddingModel.embed_text with task_type=RETRIEVAL_QUERY, reused as-is; no duplicate
   embedding client).
   Note: the ticket text says "OpenAIEmbeddingModel" but the repo's actual current embedding
   infra (post-US-308) is GeminiEmbeddingModel/build_embedding_model - this change reuses that
   real implementation, not a nonexistent OpenAI one.
2. Retrieves top-K knowledge_documents rows filtered by organization_id + approved=true
   (+ category when provided), ranked by pgvector cosine distance on Postgres; a pure-Python
   cosine-distance fallback ranks the same filtered set when the dialect isn't Postgres (SQLite
   tests), so the service is fully testable without a real Postgres/pgvector instance - mirrors
   PropertyRepository.semantic_search's dialect gate, but resolved inside the repository.
3. Assembles answer_text EXTRACTIVELY: concatenates the top passage(s) content (trimmed) with
   a light connective phrase - never calls an LLM to freely generate prose beyond retrieved
   content. This is the deterministic guarantee behind "sin cifras no verificadas" (Regla 2/QA-6).
   A Protocol-based seam (AnswerPhraserPort, matching ExplanationGenerator/SignalPhraser's shape
   in recommendation/application/explanation_generator.py) is left for a future LLM-backed
   phraser that still must not introduce new figures - out of scope to implement now.
4. Empty KB / no match: returns KnowledgeAnswer with a no-info template, empty
   source_document_ids, the requested category, and found=False - never raises.

Repository also exposes add_document(document) so the service is testable end-to-end via seeded
documents, without an ingestion pipeline (out of scope - no bulk ingestion UI/endpoint here).

### Files to modify / add

- New: app/modules/knowledge/__init__.py, domain/models.py, domain/__init__.py,
  application/knowledge_service.py, application/__init__.py,
  infrastructure/db_models.py, infrastructure/repository.py, infrastructure/__init__.py
- New: alembic/versions/0020_knowledge_documents.py (head is 0019_outbox_retry_backoff)
- New: tests/test_knowledge_service.py
- New: openspec/changes/knowledge-rag-service-ai-106/proposal.md, design.md, tasks.md,
  specs/knowledge-rag/spec.md
- Not modified: CoordinatorAgent, qualification_flow.py, lead_scoring.py (AI-105 wiring is
  future work, explicit non-goal here)

### Definition of done

- KnowledgeService.answer embeds the query, retrieves only approved + org-scoped passages, and
  assembles an answer using only retrieved content.
- Category filter narrows retrieval when provided.
- Cross-tenant isolation: a document in another organization_id is never retrievable.
- Empty KB / no-match returns a clear found=False result, no exception.
- Migration 0020 creates knowledge_documents with vector(1536) + HNSW index on Postgres,
  portable on SQLite for tests (same pattern as 0011/0013).
- tests/test_knowledge_service.py passes under the repo's pytest invocation without a live
  Postgres/pgvector instance or network access (deterministic embedder, no gemini_api_key
  required).
- tasks.md checklist fully checked off.

### Docs / test updates

- openspec/changes/knowledge-rag-service-ai-106/specs/knowledge-rag/spec.md - new capability
  spec (ADDED requirements), following the intent-routing archived-change structure.
- Unit tests cover: approved-only retrieval, organization isolation, category filter, grounding
  (no invented content), empty-KB handling.

### Non-functional requirements

- Security / tenant isolation: every repository query filters by organization_id; no
  cross-tenant leakage possible even with a matching embedding.
- Determinism / no hallucinated figures: extractive answer assembly is a hard constraint - not
  a best-effort prompt instruction - satisfies "sin cifras no verificadas" (Regla 2/QA-6).
- Hermetic tests: default to a deterministic embedder (no API key, no network) exactly like
  HashEmbeddingModel, so CI never depends on Gemini availability.
- Observability: out of scope for this change (no AIDecisionTrace integration yet - there is
  no caller/turn to attach a trace to until the AI-105 wiring change exists).
