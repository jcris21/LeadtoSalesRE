## Why

Sprint 3.1 closes the three infrastructure/persistence gaps of the Recommendation engine. US-309 is an active bug (🔴 max priority of the whole phase): the `properties` ORM expects a `zone` column while the real Supabase database has `District`/`name_address`/`Link_references`/`estado` added manually outside Alembic, so the Structured Filter breaks against real Postgres. US-308 replaces the 16-dim `HashEmbeddingModel` stand-in so semantic similarity becomes meaningful (blocks US-304). US-310 persists the currently-ephemeral `RecommendationResult` for auditability and the learning loop (closes backlog US-301).

## What Changes

- **US-309**: state-conditional migration `0010` reconciling `properties` (rename `zone`/`District` → `district`, formalize `name_address` text, `estado` text, `link_references` jsonb); `PropertyORM.zone` maps to column `district`; domain `Property` gains the three new optional fields; ingestion `content_hash` inputs unchanged (no mass re-embed).
- **US-308**: `OpenAIEmbeddingModel` (httpx, `text-embedding-3-small`, 1536 dims) behind the existing `EmbeddingModel` seam, which becomes async; new `openai_api_key` setting; wiring falls back to `HashEmbeddingModel` (logged) when no key is configured so tests stay hermetic. Migration `0011`: `CREATE EXTENSION vector` + `property_embeddings.vector` jsonb → `vector(1536)` on Postgres (ORM stays portable JSON; the `<->` operator is US-304 / Sprint 3.2 scope).
- **US-310**: migration `0012` creating `recommendations` (one row per ranked property: rank, score, `signals` jsonb, explanation, `neighborhood` jsonb, `feedback` jsonb, `generated_at`, `delivered_at`, RLS by organization); `RecommendationItem` gains `signals`; new `RecommendationRepository`; `RecommendationService` persists via an optional structural `recommendation_store` port; `wiring.handle_profile_completed` marks `delivered_at` after publishing `ResponseReady`.

## Capabilities

### New Capabilities

- `property-catalog`: reconciled `properties` schema — `district` (snake_case), `name_address`, `estado`, `link_references` jsonb — consistent across ORM, domain, and migrations (US-309).
- `property-embeddings`: real 1536-dim embedding generation (`text-embedding-3-small`) behind the async `EmbeddingModel` seam with deterministic fallback, and `vector(1536)` storage on Postgres (US-308).
- `recommendation-persistence`: audited storage of every recommendation search — one `recommendations` row per ranked property with signals, explanation, neighborhood, delivery and feedback lifecycle (US-310).

### Modified Capabilities

<!-- none — existing specs (affinity-profile, conversation-memory, lead-qualification*) are untouched; the recommendation pipeline had no main spec yet. -->

## Impact

- **Code**: `recommendation/infrastructure/db_models.py` (PropertyORM column mapping + RecommendationORM), `domain/models.py` (Property fields, RecommendationItem.signals), `infrastructure/repository.py` (property field mapping + RecommendationRepository), new `infrastructure/embedding_model.py`, `application/property_ingestion.py` (async seam), `application/recommendation_service.py` (optional store), `wiring.py` (store + delivered_at + embedder selection), `core/config.py` (`openai_api_key`).
- **Schema**: migrations `0010` (properties reconciliation, conditional on drift state), `0011` (pgvector extension + vector(1536)), `0012` (recommendations + RLS).
- **Tests**: new suites for property schema mapping, OpenAI client (mocked transport), recommendation persistence; existing retrieval/ranking/ingestion suites keep passing.
- **Docs**: US-308/309/310 flip from GAP to implemented in `HU_Calificacion_Recomendacion.md`.
- **Risk**: migration 0010 must handle two divergent starting states (fresh 0004 DB vs drifted Supabase); mitigated with inspector-based conditional DDL.
