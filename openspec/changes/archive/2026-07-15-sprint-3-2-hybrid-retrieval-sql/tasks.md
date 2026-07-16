## 1. US-303 — SQL WHERE structured filter

- [x] 1.1 Add `PropertyRepository.filter_candidates(organization_id, *, budget, zones, property_type)` in `app/modules/recommendation/infrastructure/repository.py` — SQLAlchemy Core WHERE composition per design D2 (absent constraint = no clause; inclusive BETWEEN; `district` IN; type equality)
- [x] 1.2 Update `PropertyLookup` protocol and `StructuredFilterService.filter_candidates` in `app/modules/recommendation/application/retrieval.py` to delegate to the new query (drop the `list_for_organization` + Python filter path)
- [x] 1.3 Tests: SQL parity with `matches_hard_filters` (with/without budget, zones, type), tenant scoping, and no `list_for_organization` call

## 2. US-304 — pgvector semantic retrieval

- [x] 2.1 Write migration `alembic/versions/0013_sprint3_2_hnsw_index.py`: `CREATE INDEX ix_property_embeddings_vector_hnsw ON property_embeddings USING hnsw (vector vector_cosine_ops)`; downgrade drops it
- [x] 2.2 Add `PropertyRepository.semantic_search(candidate_ids, query_vector, top_n)` — dialect-gated per design D3 (`<->` ORDER BY on postgresql, `None` elsewhere)
- [x] 2.3 Update `SemanticRetrievalService.retrieve` to try the SQL path first (design D4), keeping the in-memory fallback and the no-embedding exclusion
- [x] 2.4 Tests: SQL path selected when store supports it (in-memory cosine never invoked, `top_n` honored); existing `test_hybrid_retrieval.py` fallback suite stays green

## 3. Docs & verification

- [x] 3.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md`: US-303/US-304 headings + alignment (d) to implemented; traceability rows to Sí
- [x] 3.2 Full test suite + ruff on touched files; offline `alembic upgrade 0012:0013 --sql` and downgrade verified
