## Context

`property_embeddings` (US-308) already proves the pattern this change reuses: an async
`EmbeddingModel` seam with a `GeminiEmbeddingModel` production implementation and a deterministic
`HashEmbeddingModel` fallback, `vector(1536)` storage on Postgres via a dialect-gated raw-SQL
insert/query path, and a portable `JSON` column so the same ORM model runs on SQLite in tests.
`AI-106` needs the same shape for a different corpus (approved knowledge passages, not properties),
so this design copies the pattern instead of inventing a new one.

## Goals / Non-Goals

**Goals:**
- A `knowledge_documents` table storing approved, organization-scoped, categorized passages with
  a 1536-dim embedding.
- `KnowledgeService.answer` that embeds a query, retrieves top-K approved passages (org + optional
  category filtered), and assembles a grounded answer using only retrieved passage text.
- Full testability without Postgres/pgvector or network access (SQLite + deterministic embedder).
- Reuse of the existing embedding infrastructure (`GeminiEmbeddingModel`/`build_embedding_model`),
  not a duplicate client.

**Non-Goals:**
- Wiring into `CoordinatorAgent` / any Intent Router (see proposal.md).
- An LLM-backed answer phraser (a `Protocol` seam is left for one, not implemented).
- A document ingestion/authoring UI or bulk-import pipeline - `add_document` is the only write
  path, sufficient for tests and manual seeding.
- `AIDecisionTrace` integration - no turn exists yet to attach a trace to.

## Data Model

`knowledge_documents`:
- `id` uuid PK
- `organization_id` uuid FK organizations.id ON DELETE CASCADE, indexed
- `title` varchar(255)
- `content` text
- `category` varchar(32) - one of `precio | zona | plusvalia | financiamiento | general`
- `embedding` vector(1536) on Postgres (portable JSON on SQLite) - same dual typing as
  `property_embeddings.vector`
- `approved` boolean, default false
- `created_at` timestamptz

No `source_hash`/`computed_at` change-detection columns like `property_embeddings` - knowledge
documents are authored content, not a mirrored external catalog; `add_document` re-embeds on every
call, which is acceptable at KB scale (small, curated corpus, not a syncing pipeline).

## Retrieval Flow

1. `KnowledgeService.answer` calls the embedding seam's `embed_text(query, task_type=
   RETRIEVAL_QUERY)` (or the deterministic test embedder) to get a 1536-dim (or N-dim in tests)
   query vector.
2. `KnowledgeRepository.find_similar(organization_id, query_vector, category, top_k)`:
   - Postgres: `SELECT ... WHERE organization_id = :org AND approved = true
     [AND category = :category] ORDER BY embedding <-> :query_vector LIMIT :top_k`, mirroring
     `PropertyRepository.semantic_search`'s dialect-gated raw SQL with an explicit vector cast.
   - SQLite (tests): loads the same filtered candidate set via the ORM, computes cosine distance
     in Python, and returns the top-K sorted ascending - the *service* never needs to know which
     path ran; both return the same ordered `KnowledgeDocument` list shape.
3. `_assemble_answer(passages)`: extractive assembly - joins the top passage(s)' `content`
   (trimmed) with a fixed connective phrase. No LLM call, no free-text generation: the answer
   string is provably a subset/concatenation of retrieved, approved content.
4. Empty result set (no approved docs match org/category, or KB is empty) -> `KnowledgeAnswer`
   with a static "no information found" template, empty `source_document_ids`, `found=False`.

## Decisions

**Extractive assembly, not LLM generation (hard constraint)**: the ticket's Regla 2/QA-6 ("sin
cifras no verificadas") is satisfied structurally, not by prompting. `_assemble_answer` only
concatenates/trims retrieved `content` strings - it cannot introduce a number, price, or fact that
was not already present in an approved passage. A `Protocol` seam (`AnswerPhraserPort`) is defined
for a future LLM-backed rephraser, matching `ExplanationGenerator`'s shape in
`recommendation/application/explanation_generator.py`, but no implementation ships here; wiring one
in later would still need its own grounding safeguard, out of scope now.

**Reuse `GeminiEmbeddingModel`, not a new client**: the ticket text mentions
"OpenAIEmbeddingModel", which does not exist in this repo (the actual current embedding
infrastructure, post-US-308, is `GeminiEmbeddingModel`/`build_embedding_model`). This design reuses
that real implementation via its already-generic `embed_text(text, task_type=...)` method - no new
HTTP client, no new retry/backoff logic duplicated.

**SQLite fallback resolved inside the repository, not the service**: unlike
`SemanticRetrievalService`/`PropertyRepository.semantic_search` (which return `None` on non-Postgres
and let the caller fall back to a separate in-memory ranking component), this module has no
existing hybrid-retrieval component to reuse for that fallback. Since the KB corpus is expected to
be small, the repository itself computes cosine distance in Python when the dialect isn't
Postgres, and always returns an ordered list - simpler for a first cut, with the same net testing
guarantee (no Postgres/pgvector required to test ranking correctness).

**Category as a plain string column, own enum**: `KnowledgeCategory` is a new `StrEnum`
(`precio | zona | plusvalia | financiamiento | general`), not a reuse of `ObjectionType` -
`ObjectionType` has `tamano`/`tiempo` (no KB counterpart) and lacks `plusvalia`/`general`. Coupling
the two would force one enum to serve two different, only-partially-overlapping concerns.

**No embedding on unapproved documents' retrieval, but embedding still computed on add**:
`approved` gates retrieval (`WHERE approved = true`), not embedding computation - a document can be
authored/embedded and reviewed before being flipped to `approved = true`, without a second write
path.

## Risks / Trade-offs

- [Risk: SQLite Python-side cosine fallback could silently diverge from Postgres `<->` ordering
  for edge cases like exact ties] -> Mitigation: both paths order by the same cosine-distance
  definition; tests assert relative ranking (nearest passage first), not exact floating-point
  equality, which is robust to the two implementations.
- [Risk: extractive assembly can read as less natural than free-form LLM prose] -> Mitigation:
  explicitly the point (Regla 2/QA-6 compliance over fluency); the `AnswerPhraserPort` seam is the
  documented upgrade path once a grounded-rephrasing design exists.
- [Risk: `add_document` re-embeds every call, no dedup/idempotency] -> Mitigation: acceptable at
  authoring/seeding scale; if a bulk-ingestion pipeline is added later it can reuse the same
  content-hash technique as `PropertyIngestionService` without changing this service's contract.

## Migration Plan

Additive only: new table, new module, no changes to existing tables or code paths. Deploying with
no `gemini_api_key` configured still works - `KnowledgeService` falls back to a deterministic
embedder (mirrors `build_embedding_model`'s existing keyless behavior) so this ships safely with no
coordinated config change. Rollback is a plain `alembic downgrade` of `0020` plus reverting the new
module; nothing else references it yet.
