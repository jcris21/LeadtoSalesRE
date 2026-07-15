## 1. Domain model

- [x] 1.1 Add `FinancingType` enum (`CASH`, `MORTGAGE_APPROVED`, `MORTGAGE_PREAPPROVED`, `EVALUATING`) to `app/modules/lead_qualification/domain/models.py`
- [x] 1.2 Add `DecisionMakerMode` enum (`SOLO`, `COUPLE`, `FAMILY`) to the same module
- [x] 1.3 Extend `PROFILE_DIMENSIONS` tuple to 7 elements, adding `"financing_type"` and `"decision_maker_mode"`
- [x] 1.4 Add `financing_type: FinancingType | None = None` and `decision_maker_mode: DecisionMakerMode | None = None` to `ProfilePatch`
- [x] 1.5 Add the two fields to `BuyerProfile.__init__`, `.apply()`, and `.captured_dimensions()`

## 2. Extraction

- [x] 2.1 Add `extract_financing_and_decision_mode` to `qualification_flow.py`, mirroring `extract_timeline_and_must_haves` (single combined extractor, both fields optional in one `ProfilePatch`)
- [x] 2.2 Add Spanish keyword tables for financing (`contado`, `crédito hipotecario`, `crédito preaprobado`, `evaluando`) and decision mode (`solo`, `en pareja`, `con mi familia`/`con mi esposa`/`con mi esposo`)
- [x] 2.3 Ensure `_assert_tenant` is called before persisting, consistent with existing extractors

## 3. Application service

- [x] 3.1 Update `BuyerProfileCaptureService._snapshot()` to include `financing_type` and `decision_maker_mode`

## 4. Persistence

- [x] 4.1 Add Alembic migration `0006_sprint2_1_buyer_profile_dimensions.py` — nullable `financing_type`, `decision_maker_mode` columns on `buyer_profiles`, with reversible `downgrade()`
- [x] 4.2 Update `BuyerProfileRepository` (and ORM model in `infrastructure/repository.py` / `db_models.py`) to map the two new columns

## 5. API surface

- [x] 5.1 If `api/schemas.py` exposes a profile read model, add the two nullable fields — checked: `api/schemas.py` only exposes `ProfileCaptureResponse.captured_dimensions` (a generic dimension-name list), no per-field read model exists, so no change was needed here.

## 6. Tests

- [x] 6.1 Unit tests in `tests/test_buyer_profile.py`: `completeness()` over 7 dimensions, `captured_dimensions()` includes new fields, `apply()` patch semantics for the two new fields
- [x] 6.2 Unit tests in `tests/test_qualification_flow.py`: financing keyword extraction, decision-mode keyword extraction, combined-patch extraction, no-signal case returns `None`
- [x] 6.3 Regression test: a profile with only the original 5 dimensions captured no longer reports 100% completeness

## 7. Documentation

- [x] 7.1 Add/update `openspec/specs/lead-qualification/spec.md` delta (already drafted as part of this proposal)
- [x] 7.2 Remove `[GAP — no implementado]` marker for US-208 in `Documents/Oficial/HU_Calificacion_Recomendacion.md`

## 8. Verification

- [x] 8.1 Run `alembic upgrade head` then `alembic downgrade -1` to confirm migration reversibility — no live Postgres reachable in this sandbox (`alembic/env.py` requires `settings.database_url`, asyncpg driver); verified instead that the migration module imports cleanly, `revision="0006"`/`down_revision="0005"` chain correctly off `0005_sprint3_lead_conversation_link.py`, and both `upgrade()`/`downgrade()` are syntactically valid, symmetric `add_column`/`drop_column` pairs.
- [x] 8.2 Run full test suite (`pytest`) and confirm no regression in existing qualification/buyer-profile tests — all tests in `test_buyer_profile.py`, `test_qualification_flow.py`, `test_recommendation_service.py`, `test_recommendation_wiring.py` pass (59/59). Two downstream fixtures (`_complete_profile` in `test_recommendation_service.py` and `test_recommendation_wiring.py`) were updated to also set `financing_type`/`decision_maker_mode` since the completeness denominator grew from 5 to 7.
