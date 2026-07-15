## 1. Schema

- [x] 1.1 Add `ai_profile: Mapped[dict | None]` (JSON, nullable) to `BuyerProfileORM` and `buyer_persona: Mapped[dict | None]` (JSON, nullable) to `LeadORM` in `app/modules/lead_qualification/infrastructure/db_models.py`, with docstrings noting US-211 ownership (aggregator is the sole writer; not CRM-mirrored, CON-2 unaffected)
- [x] 1.2 Create Alembic migration `alembic/versions/0009_sprint2_2_affinity_profile.py` adding both nullable JSON columns, with symmetric downgrade

## 2. Repository

- [x] 2.1 Add `list_for_lead(lead_id, *, min_confidence)` to `ConversationMemoryRepository` in `app/modules/conversation_memory/infrastructure/repository.py`, ordered by `created_at`

## 3. Aggregation service (TDD)

- [x] 3.1 Write failing tests in `tests/test_profile_aggregation.py` (same aiosqlite harness as `tests/test_conversation_memory.py`) covering: happy path writes both snapshots with expected shapes; below-threshold observations excluded; no eligible observations → no write, existing snapshots untouched; idempotency (same observation set → same scores); snapshot independence (qualification dimensions and `conversation_memory` rows unchanged); lead without `buyer_profiles` row → only `buyer_persona` written, no profile created; cross-tenant → `LeadNotFoundError`, nothing written
- [x] 3.2 Implement `ProfileAggregationService.aggregate(session, *, lead_id, organization_id)` in `app/modules/conversation_memory/application/profile_aggregation.py` per design D1–D7: `_MIN_CONFIDENCE = 0.5`, `_assert_tenant`, deterministic `modern_score`/`family_score` derivation, categorical `buyer_persona` mapping (`family_stage`, `has_pets`, `communication="whatsapp"`), `computed_at` ISO-8601 UTC, graceful skip of `ai_profile` when no profile row
- [x] 3.3 Run the new test suite to green; then run the full test suite to confirm no regression

## 4. Documentation & verification

- [x] 4.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md`: US-211 heading and alignment note (d) from GAP to implemented (mirror the AI-102/US-208/US-209 wording pattern), and the traceability table row (US-211 → Sí)
- [x] 4.2 Verify migration up/down (offline SQL generation: `alembic upgrade 0008:0009 --sql` / `downgrade 0009:0008 --sql` — ALTERs correctos y simétricos; no hay Postgres scratch local) against a scratch database (`alembic upgrade head` / `alembic downgrade -1`)
- [x] 4.3 Run linters/formatters used by the repo (ruff/black) on touched files
