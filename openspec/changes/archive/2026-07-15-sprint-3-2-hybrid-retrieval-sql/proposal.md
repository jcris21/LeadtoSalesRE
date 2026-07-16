## Why

Sprint 3.2 makes Hybrid Retrieval real. The Structured Filter still loads the whole organization's catalog into Python and filters in a list comprehension (US-303), and Semantic Retrieval computes cosine similarity in-process (US-304) — neither scales past small catalogs, and both were explicitly designed as stand-ins pending US-309/US-308, which Sprint 3.1 just landed (reconciled `properties` schema, `vector(1536)` column).

## What Changes

- **US-303**: `PropertyRepository.filter_candidates(...)` builds a SQL `WHERE` (org + optional price BETWEEN + district IN + property_type =) with semantics identical to `Property.matches_hard_filters`; `StructuredFilterService` delegates to it instead of `list_for_organization()` + Python filtering. `matches_hard_filters` stays as the domain's executable specification.
- **US-304**: migration `0013` adds the HNSW index (`vector_cosine_ops`); `PropertyRepository.semantic_search(candidate_ids, query_vector, top_n)` orders by pgvector `<->` on Postgres and returns `None` on other dialects; `SemanticRetrievalService.retrieve` uses the SQL path when supported (no Python cosine) and keeps the in-memory fallback for SQLite/fakes (documented repo trade-off). `embed_query` stays injectable.

## Capabilities

### New Capabilities

- `hybrid-retrieval`: two-stage candidate selection — hard-constraint filtering pushed down to SQL `WHERE`, and semantic ranking via pgvector `<->` with HNSW index on Postgres (in-memory fallback only where the dialect lacks pgvector).

### Modified Capabilities

<!-- none — property-catalog/property-embeddings requirements are unchanged; this change adds the retrieval capability that consumes them. -->

## Impact

- **Code**: `recommendation/infrastructure/repository.py` (two new query methods), `application/retrieval.py` (delegation + SQL-first branch), `domain/ports`-level protocols unchanged (PropertyLookup protocol in retrieval.py gains the new signatures).
- **Schema**: migration `0013` (HNSW index only — column type landed in 0011).
- **Tests**: new suite for SQL filter parity and SQL-path selection; existing `test_hybrid_retrieval.py` keeps passing (fallback path).
- **Docs**: US-303/US-304 flip from GAP-parcial to implemented.
