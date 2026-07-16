## Context

`retrieval.py` implements Hybrid Retrieval with documented stand-ins: `StructuredFilterService` fetches `list_for_organization()` and filters via `Property.matches_hard_filters` in Python; `SemanticRetrievalService` scores with `_cosine_similarity` in-process. Sprint 3.1 delivered the prerequisites: `properties` is reconciled (US-309, `district` column) and `property_embeddings.vector` is `vector(1536)` on Postgres (US-308). Tests run on aiosqlite, which has no pgvector.

## Goals / Non-Goals

**Goals:**
- Hard-constraint filtering as a SQL `WHERE` with semantics identical to `matches_hard_filters`.
- Semantic ranking via pgvector `<->` (cosine ops) with an HNSW index on Postgres; zero Python cosine on that path.
- Existing test harness stays hermetic (SQLite).

**Non-Goals:**
- No real query-embedding for BuyerProfile (`embed_query` stays injectable; quality is future scope — the operator is this change's scope).
- No changes to Ranking/Explanation/Enrichment or the `RecommendationPort` facade.
- No pagination or ANN tuning (ef_search etc.) — defaults suffice at MVP volume.

## Decisions

**D1 — Both new queries live on `PropertyRepository`; the `PropertyLookup` protocol in `retrieval.py` grows the same signatures.** Structural typing keeps `retrieval.py` DB-free, mirroring how the module was built.

**D2 — `filter_candidates` composes conditions exactly like `matches_hard_filters`:** absent constraint ⇒ no clause (`budget is None`, empty `zones`, `property_type is None`); price uses inclusive BETWEEN; zones use `IN`; always scoped by `organization_id`. Portable SQLAlchemy Core (runs on SQLite and Postgres) — no dialect branch needed for US-303.

**D3 — `semantic_search` is dialect-gated and returns `list[Property] | None`.** On `postgresql` it runs `SELECT p.* FROM properties p JOIN property_embeddings e ... WHERE p.id IN (:candidates) ORDER BY e.vector <-> CAST(:query AS vector) LIMIT :top_n`; on any other dialect it returns `None`, signalling "unsupported". Rationale: the service (not the repo) owns the fallback decision, and fakes/SQLite naturally take the fallback path with no special-casing.

**D4 — `SemanticRetrievalService.retrieve` tries SQL first.** If the store exposes `semantic_search` and it returns a list, that IS the result (no `_cosine_similarity` call — satisfies the HU verbatim on Postgres). Otherwise the existing in-memory path runs — same accepted SQLite trade-off as every JSON column in the repo; branch logged at debug.

**D5 — `<->` with `vector_cosine_ops` preserves today's ranking semantics.** The in-memory path ranks by cosine similarity descending; cosine distance ascending is the same order, so both paths agree — asserted in tests via the fallback.

**D6 — Migration `0013` creates only the HNSW index** (`USING hnsw (vector vector_cosine_ops)`); the column type landed in 0011. Downgrade drops the index. Offline `--sql` friendly (plain DDL, no inspector).

## Risks / Trade-offs

- [SQLite path still computes cosine in Python] → Accepted, documented: production dialect is Postgres; the HU's "no Python cosine" holds on the real deployment target.
- [`IN (:candidates)` with many ids] → Bounded by Structured Filter output at MVP volume; revisit with a temp-join if catalogs grow.
- [HNSW build cost on existing data] → Table is small today; index builds in ms. `CREATE INDEX` is not CONCURRENTLY — acceptable pre-production.

## Migration Plan

1. `0013` HNSW index (independent, reversible).
2. Code deploy — behavior on Postgres switches to SQL paths automatically; SQLite/dev unchanged.
3. Rollback: revert code; optionally downgrade 0013.

## Open Questions

- None blocking.
