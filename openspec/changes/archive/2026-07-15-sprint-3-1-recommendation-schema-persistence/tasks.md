## 1. US-309 — Properties schema reconciliation (max priority)

- [x] 1.1 Update `PropertyORM`: map attribute `zone` to column `district` (`mapped_column("district", ...)`); add `name_address` (String nullable), `estado` (String nullable), `link_references` (JSON default list) in `app/modules/recommendation/infrastructure/db_models.py`
- [x] 1.2 Extend domain `Property` with `name_address: str | None = None`, `estado: str | None = None`, `link_references: tuple[str, ...] = ()` in `app/modules/recommendation/domain/models.py`; confirm `_content_key` in `property_ingestion.py` is untouched (D3)
- [x] 1.3 Map the new fields in `PropertyRepository.upsert/_to_domain` (`app/modules/recommendation/infrastructure/repository.py`)
- [x] 1.4 Write migration `alembic/versions/0010_sprint3_1_properties_reconciliation.py`: inspector-based conditional (fresh: rename `zone`→`district`, add 3 columns; drifted: rename `District`→`district`, `Link_references`→`link_references` text→jsonb with USING wrap, add missing columns only); symmetric downgrade to 0004 shape
- [x] 1.5 Tests: property round-trip with new fields; existing retrieval/ranking/ingestion suites green; migration validated via offline `alembic upgrade 0009:0010 --sql` and downgrade

## 2. US-308 — Real embedding model

- [x] 2.1 Make `EmbeddingModel.embed` async (protocol + `HashEmbeddingModel` + `await` in `PropertyIngestionService.ingest_from_source`); update affected tests
- [x] 2.2 Add `openai_api_key: str | None = None` to `app/core/config.py`
- [x] 2.3 Implement `OpenAIEmbeddingModel` in `app/modules/recommendation/infrastructure/embedding_model.py`: httpx POST to `/v1/embeddings`, model `text-embedding-3-small`, embed text = description+features+district+type, one retry on 429/5xx, raise on final failure, `model_version = "text-embedding-3-small"`
- [x] 2.4 Wire embedder selection where ingestion is constructed: real model when key set, else `HashEmbeddingModel` + warning log
- [x] 2.5 Write migration `alembic/versions/0011_sprint3_1_embeddings_vector.py`: `CREATE EXTENSION IF NOT EXISTS vector`; delete `model_version='hash-v1'` rows; `ALTER COLUMN vector TYPE vector(1536)`; downgrade back to jsonb
- [x] 2.6 Tests: OpenAI client with mocked httpx transport (correct payload, 1536 floats returned, retry-then-raise); hash-gated recompute unchanged; suite green

## 3. US-310 — Recommendations persistence

- [x] 3.1 Add `signals: tuple[RankingSignal, ...] = ()` to `RecommendationItem`; thread signals from ranked candidates in `RecommendationService.search()`
- [x] 3.2 Add `RecommendationORM` to `recommendation/infrastructure/db_models.py` (id, organization_id FK, lead_id FK, buyer_profile_id FK nullable, property_id FK, rank, score, signals JSON, explanation, neighborhood JSON nullable, feedback JSON nullable, generated_at, delivered_at nullable; indexes on lead_id and generated_at)
- [x] 3.3 Write migration `alembic/versions/0012_sprint3_1_recommendations.py` with RLS policy per 0004 pattern
- [x] 3.4 Implement `RecommendationRepository` (`save_result(organization_id, buyer_profile_id, result)` one row per item; `mark_delivered(lead_id, generated_at)`; `list_for_lead(lead_id)`)
- [x] 3.5 Add optional structural `recommendation_store` to `RecommendationService`; persist before returning when items exist; update `wiring.handle_profile_completed` to pass the repository (with buyer_profile_id) and call `mark_delivered` after publishing `ResponseReady`
- [x] 3.6 Tests: rows per item with signals/explanation/neighborhood; empty result inserts nothing; no store = no persistence; delivered_at only after delivery; suite green

## 4. Docs & verification

- [x] 4.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md`: US-308/309/310 headings + alignment (d) from GAP to implemented; traceability table rows to Sí
- [x] 4.2 Full test suite + ruff on touched files; offline SQL generation for 0010/0011/0012 up and down
