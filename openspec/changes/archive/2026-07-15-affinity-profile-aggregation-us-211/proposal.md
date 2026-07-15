## Why

AI-102 (Sprint 2.1) writes free-text conversational signals into the append-only `conversation_memory` table, but nothing consumes it yet: the Ranking Engine (US-305) still ranks on budget/zone/type only, and the future Coordinator (AI-104) has no per-lead communication-context snapshot. US-211 closes this gap — the last HU of Sprint 2.2 and the final Definition-of-Done item for the Qualification phase ("perfil de afinidad disponible como señal para el Ranking Engine").

## What Changes

- New `ProfileAggregationService` (`app/modules/conversation_memory/application/profile_aggregation.py`) that synthesizes a lead's `conversation_memory` rows (above a confidence threshold) into two independent jsonb snapshots.
- New column `buyer_profiles.ai_profile` (JSON, nullable): deterministic affinity scores (`modern_score`, `family_score`, aggregate `confidence`, `observation_count`, `computed_at`) for the Ranking Engine.
- New column `leads.buyer_persona` (JSON, nullable): communication/context signals (`family_stage`, `has_pets`, `communication`, `computed_at`) for the Coordinator's conversational tone.
- Alembic migration `0009_sprint2_2_affinity_profile` adding both columns.
- Recompute-on-write trigger contract: the aggregator runs only after `extract_conversation_memory` returns new observations — never on the read/search path. No scheduler.
- Invariants: neither snapshot overwrites the other (distinct owners/consumers); neither touches the closed-enum `PROFILE_DIMENSIONS` / US-208 dimensions; `conversation_memory` stays append-only and un-consumed by the completeness gate.

## Capabilities

### New Capabilities

- `affinity-profile`: aggregation of `conversation_memory` observations into the `buyer_profiles.ai_profile` and `leads.buyer_persona` snapshots — eligibility threshold, deterministic score derivation, snapshot independence, recompute trigger, and tenant isolation.

### Modified Capabilities

<!-- none — conversation-memory extraction requirements are unchanged; this change only adds a downstream consumer. lead-qualification requirements (PROFILE_DIMENSIONS, completeness) are explicitly untouched. -->

## Impact

- **Code**: new module file in `app/modules/conversation_memory/application/`; new repository query (`list_for_lead` with min-confidence filter) in `conversation_memory/infrastructure/repository.py`; new ORM columns on `BuyerProfileORM` and `LeadORM` in `lead_qualification/infrastructure/db_models.py`.
- **Schema**: `buyer_profiles.ai_profile` jsonb, `leads.buyer_persona` jsonb (both nullable; portable `JSON` type per existing SQLite-test convention). Migration `0009`.
- **Consumers (future, not in scope)**: US-305 Ranking Engine reads `ai_profile` as an additional signal; AI-104 Coordinator reads `buyer_persona`. Both are non-blocking per ImplementationPlan ("mejora opcionalmente el Ranking Engine — no bloqueante").
- **Docs**: `Documents/Oficial/HU_Calificacion_Recomendacion.md` US-211 alignment note (d) flips from GAP to implemented.
- **Tests**: new `tests/test_profile_aggregation.py` (pytest + aiosqlite harness, same as `test_conversation_memory.py`).
