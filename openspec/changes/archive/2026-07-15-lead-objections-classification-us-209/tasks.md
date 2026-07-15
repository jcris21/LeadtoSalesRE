## 1. Domain model

- [x] 1.1 Add `ObjectionType` enum (`PRECIO`, `ZONA`, `FINANCIAMIENTO`, `TAMANO`, `TIEMPO`) to `app/modules/lead_qualification/domain/models.py`
- [x] 1.2 Add `LeadClassification` enum (`HOT`, `WARM`, `COLD`)
- [x] 1.3 Add `Objection` entity (`id`, `lead_id`, `organization_id`, `type: ObjectionType`, `raw_text`, `created_at`)
- [x] 1.4 Add `Lead.lead_classification: LeadClassification` field, defaulting to `LeadClassification.HOT` on construction
- [x] 1.5 Add `ObjectionRecorded` domain event (mirrors `ProfileCompleted`/`CRMStageSynced` shape: `lead_id`, `crm_lead_id`, `objection_type`, `lead_score`, `lead_classification`)

## 2. Scoring service

- [x] 2.1 Add `app/modules/lead_qualification/application/lead_scoring.py` with `LeadScoringService.record_objection(lead_id, objection_type, raw_text) -> (lead_score, lead_classification)`
- [x] 2.2 Implement `compute_lead_score(distinct_objection_types: int, total_objection_count: int) -> float` per design.md Decision 1 formula
- [x] 2.3 Implement `classify(lead_score: float) -> LeadClassification` per design.md thresholds (>=70 Hot, 40-69.99 Warm, <40 Cold)
- [x] 2.4 `record_objection` persists the `Objection` row, updates `Lead.lead_score`/`lead_classification`, and publishes `ObjectionRecorded` via the event bus — same transactional style as `BuyerProfileCaptureService.update_profile`

## 3. Extraction

- [x] 3.1 Add `extract_objection` to `qualification_flow.py`: single best-match closed-enum extractor (mirrors `extract_property_type`), Spanish keyword tables per `ObjectionType`
- [x] 3.2 Keyword tables per `ObjectionType` (Precio, Zona, Financiamiento, Tamaño, Tiempo)
- [x] 3.3 Ensure `_assert_tenant` is called before persisting, consistent with existing extractors
- [x] 3.4 `extract_objection` calls `LeadScoringService.record_objection` (not `BuyerProfileCaptureService` — objections are not a `BuyerProfile` dimension)

## 4. Persistence

- [x] 4.1 Add `LeadObjectionORM` to `db_models.py` (table `lead_objections`)
- [x] 4.2 Add `lead_classification` column to `LeadORM`
- [x] 4.3 Add Alembic migration `0007_sprint2_1_lead_objections.py` (down_revision `0006`) — create `lead_objections` table, add `leads.lead_classification` (nullable at deploy via server_default `'hot'`, then not-null), reversible `downgrade()`
- [x] 4.4 Add `LeadObjectionRepository` (`add`, `list_for_lead`, `count_for_lead`, `count_distinct_types_for_lead`) to `infrastructure/repository.py`
- [x] 4.5 Update `LeadRepository._to_row`/`_to_domain`/`save` to map `lead_classification`

## 5. Tests

- [x] 5.1 `tests/test_lead_objections.py`: one happy-path extraction test per `ObjectionType` (5 tests, parametrized), one no-signal test, one tenant-isolation test
- [x] 5.2 `tests/test_lead_objections.py`: `compute_lead_score`/`classify` unit tests covering the Hot/Warm/Cold boundary scenarios from specs/lead-qualification/spec.md
- [x] 5.3 `tests/test_lead_objections.py`: integration test — recording an objection via `extract_objection` persists the row, updates `Lead.lead_score`/`lead_classification`, and publishes `ObjectionRecorded` to the outbox
- [x] 5.4 `tests/test_lead_objections.py`: repeated objections of different types keep eroding `lead_score` (not capped after the first occurrence)
- [x] 5.5 New `Lead` defaults to `lead_classification=Hot`

## 6. Documentation

- [x] 6.1 `specs/lead-qualification/spec.md` delta already drafted as part of this proposal (ADDED Requirements)
- [x] 6.2 Remove `[GAP — no implementado]` marker for US-209 in `Documents/Oficial/HU_Calificacion_Recomendacion.md`, update the summary table row

## 7. Verification

- [x] 7.1 Verify migration `0007` chains correctly off `0006` (import + structural check, since no live Postgres is reachable in this sandbox — see US-208's tasks.md 8.1 for the same caveat)
- [x] 7.2 Run full test suite (`pytest`) and confirm no regressions in existing qualification/recommendation tests — `test_buyer_profile.py`, `test_qualification_flow.py`, `test_lead_objections.py`, `test_recommendation_service.py`, `test_recommendation_wiring.py`, `test_lead_sync.py`, `test_staleness_guard.py` all pass (65/65).
