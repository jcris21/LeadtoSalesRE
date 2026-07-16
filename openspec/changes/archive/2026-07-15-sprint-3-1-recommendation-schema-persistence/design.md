## Context

The recommendation pipeline (Sprint 3A/3B) is functionally complete in Python but sits on three infrastructure gaps. (1) `properties` drifted: migration 0004 created `zone`, but the real Supabase database was hand-edited to `District` + `name_address` + `Link_references` (text) + `estado` — the ORM no longer matches production and the Structured Filter breaks there. (2) Embeddings are a 16-dim deterministic hash (`HashEmbeddingModel`), so semantic retrieval is not semantically meaningful; the plan commits to OpenAI `text-embedding-3-small` (1536 dims) stored as `vector(1536)`. (3) `RecommendationResult` is ephemeral — computed in `wiring.handle_profile_completed`, formatted into a WhatsApp message, and dropped.

Repo conventions that bind this design: portable ORM types (JSON/Uuid, no pgvector import in models — SQLite test harness), RLS-by-organization in migrations (0004 precedent), pluggable protocol seams (`EmbeddingModel`), structural typing for service dependencies (`BuyerProfileLookup` precedent), no secrets in code (pydantic settings).

## Goals / Non-Goals

**Goals:**

- One consistent `properties` schema across ORM, domain, migrations, and the real database, in snake_case, with `link_references` as jsonb.
- Real 1536-dim embeddings behind the existing seam; column type `vector(1536)` on Postgres.
- Every `search()` with ranked items leaves an auditable `recommendations` trail with signals and delivery lifecycle.

**Non-Goals:**

- No SQL `WHERE` filter rewrite (US-303) and no pgvector `<->` retrieval (US-304) — Sprint 3.2.
- No Coordinator/Intent Router (AI-104).
- No feedback capture UI/flow — `feedback` stays a nullable jsonb written by future events.
- No 3-level category/type/subtype property taxonomy (future improvement per domain model doc).
- No backfill/re-embed of existing rows in 0011 (embeddings regenerate naturally via content-hash ingestion once a real model is configured).

## Decisions

**D1 — ORM attribute `zone` maps to column `district`; the Python attribute name stays `zone`.** Renaming the attribute would touch every consumer (`matches_hard_filters`, retrieval, ranking, ingestion `_content_key`, tests) for zero behavioral gain; SQLAlchemy's `mapped_column("district", ...)` decouples attribute from column. The HU's Gherkin says exactly this ("el atributo zone del ORM mapea a la columna District"). snake_case `district` (not `District`) satisfies the ImplementationPlan's "normalizar a snake_case".

**D2 — Migration 0010 is state-conditional via `sa.inspect`.** Two legitimate starting states exist: fresh DB (0004 schema: `zone`, none of the drift columns) and drifted Supabase (`District`, `name_address`, `Link_references` text, `estado`, possibly no `zone`). The migration inspects existing columns and: renames `District`→`district` or `zone`→`district` (whichever exists); adds `name_address`/`estado` only if absent; renames `Link_references`→`link_references` converting text→jsonb with `USING` (wrapping a bare URL string into a one-element array), or adds it fresh as jsonb. Downgrade restores the 0004 shape (`district`→`zone`, drop the three columns). Alternative rejected: separate migrations per state — Alembic has one linear history; conditionals are the standard answer to out-of-band drift.

**D3 — `content_hash` inputs unchanged.** `_content_key` keeps hashing external_id/price/zone/type/features/description. Including the new fields would flip every stored hash and force a full re-embed on deploy. `name_address`/`estado`/`link_references` don't affect the semantic content the embedder consumes today. Revisit if the embedder starts consuming them.

**D4 — `EmbeddingModel.embed` becomes `async def`.** A real HTTP-backed embedder cannot be sync without blocking the loop. The protocol, `HashEmbeddingModel`, and `PropertyIngestionService` (the only caller) change together; tests update mechanically. Alternative rejected: `asyncio.to_thread` around a sync protocol — hides IO in a thread pool and fights the codebase's async-first convention.

**D5 — `OpenAIEmbeddingModel` uses httpx directly, no `openai` SDK dependency.** One endpoint (`POST https://api.openai.com/v1/embeddings`), bearer auth, `{"model": "text-embedding-3-small", "input": <description + features + district + type>}`. One retry on 429/5xx with short backoff; any final failure raises — a failed embed must not silently leave a stale vector. `model_version = "text-embedding-3-small"` feeds the existing hash-gated recompute logic. Key from `settings.openai_api_key`.

**D6 — Wiring selects the embedder: real when `openai_api_key` is set, `HashEmbeddingModel` (with a warning log) otherwise.** Keeps every test and keyless dev environment hermetic while making production behavior a pure config decision. The HU's "replace" is satisfied: with a key configured, the real model is what runs.

**D7 — Migration 0011: extension + type conversion, discarding stand-in rows.** `CREATE EXTENSION IF NOT EXISTS vector`, then `DELETE FROM property_embeddings WHERE model_version = 'hash-v1'` (16-dim hash vectors cannot become 1536-dim and are derived data, recomputable by ingestion), then `ALTER COLUMN vector TYPE vector(1536) USING vector::text::vector`. Downgrade converts back to jsonb. The ORM keeps portable `JSON` — only US-304 (Sprint 3.2) needs the typed column for `<->`.

**D8 — `recommendations` rows are written by `RecommendationService.search()`, not by wiring.** The service is the single point every caller flows through (wiring today, Coordinator in AI-104, Handoff Builder in Sprint 5) — persisting in wiring would lose audit rows the moment a second caller appears. The store is an optional structural dependency (`RecommendationStore` protocol with `save_result`), defaulting to None so facade unit tests need no DB. `delivered_at` is wiring's concern (only wiring knows `ResponseReady` was published) via `RecommendationRepository.mark_delivered`.

**D9 — `RecommendationItem` carries `signals`.** The Ranking Engine already produces `RankingSignal[]` per candidate; the service currently drops them when shaping items. Adding `signals: tuple[RankingSignal, ...] = ()` (default keeps existing constructors valid) lets persistence store the exact audit trail as `signals` jsonb (`[{"name", "weight", "value"}]`) with no fixed score columns — mirrors the domain-model doc's decision ("signals jsonb con RankingSignal[] dinámico").

**D10 — One migration per US (0010, 0011, 0012)** so each is independently revertible — US-309 may need to ship alone (active bug) without waiting on embeddings/persistence review.

## Risks / Trade-offs

- [Drifted-DB state may not match the documented variants exactly (casing, partial drift)] → Inspector-based conditionals cover the documented states and log which branch ran; an unexpected state fails loudly instead of guessing.
- [Deleting hash-v1 embedding rows loses data] → Derived stand-ins, recomputable from `properties` content via the existing hash-gated ingestion; documented in the migration docstring.
- [OpenAI call adds latency/cost to ingestion] → Ingestion is off the request path and hash-gated (only changed content re-embeds); one retry then fail keeps the loop bounded.
- [Async seam is a breaking change for out-of-tree EmbeddingModel implementers] → None exist (repo-internal protocol); all implementers updated in this change.
- [SQLite tests can't validate vector(1536) nor the rename branches] → Validated via offline `--sql` generation for the fresh-DB path (drifted-path branches reviewed by inspection); ORM-level tests stay on portable types (established repo trade-off).

## Migration Plan

1. `0010` properties reconciliation (conditional; ship first — fixes the active bug, unblocks US-303).
2. `0011` pgvector extension + vector(1536) (drops hash-v1 rows; ingestion repopulates).
3. `0012` recommendations table + RLS + indexes.
4. Code deploys with all three; without `openai_api_key` behavior is exactly today's (hash embedder), so 0011 can precede key provisioning.
5. Rollback: downgrade in reverse order; code revert restores the sync seam.

## Open Questions

- None blocking. The exact drifted column set on live Supabase should be confirmed at deploy time (`information_schema.columns`); the conditional branches cover the documented variants.
