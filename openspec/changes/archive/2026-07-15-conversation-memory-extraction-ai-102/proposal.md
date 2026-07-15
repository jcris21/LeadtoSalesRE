## Why

`BuyerProfileCaptureService` only captures the seven hard-structured `PROFILE_DIMENSIONS` (budget, locations, property_type, timeline, must_haves, financing_type, decision_maker_mode). Leads routinely say things in free text that don't fit any of those fields — style adjectives ("algo minimalista y luminoso"), family context ("tenemos dos niños pequeños"), tone — that are valuable raw material for a future affinity-profile inference (US-211, out of scope here) but have nowhere to land today. `conversation_memory` is already proposed in `Documents/Oficial/AI_Recommendation_Domain_Model.md` (§4) but does not exist in Supabase. This is a documented gap (AI-102) blocking US-211.

## What Changes

- New `conversation_memory` table (schema per `AI_Recommendation_Domain_Model.md` §4: `id`, `conversation_id`, `lead_id`, `memory_type`, `entity_name`, `value` jsonb, `confidence`, `created_at`) — no changes to `buyer_profiles`/`PROFILE_DIMENSIONS`.
- New `conversation_memory` bounded-context module (`app/modules/conversation_memory/`) with a `ConversationMemoryObservation` domain entity and `MemoryType` enum (`STYLE_PREFERENCE`, `FAMILY_CONTEXT` in this first cut — see design.md for the scoped-down decision on `TONE`).
- Deterministic keyword/pattern-based extractor `extract_conversation_memory` (same Sprint 2 pattern as every extractor in `qualification_flow.py`: Spanish keywords, no LLM call in this change) that inserts observations without touching `BuyerProfile` or `PROFILE_DIMENSIONS`.
- New Alembic migration adding `conversation_memory`, chained after `0007_sprint2_1_lead_objections`.
- Repository (`ConversationMemoryRepository`) for insert/list.

## Capabilities

### New Capabilities

- `conversation-memory`: free-text conversational signal extraction into structured, confidence-scored observations, distinct from and non-overwriting of the `lead-qualification` capability's `BuyerProfile` dimensions.

### Modified Capabilities

(none — this does not change any existing `lead-qualification` requirement; it is deliberately additive and non-interfering, per the source HU's own alignment note "(a) transversal a Discovery, corre en paralelo a PROFILE_DIMENSIONS, no reemplaza BuyerProfileCaptureService")

## Impact

- **Code**: new `app/modules/conversation_memory/` module (`domain/models.py`, `application/memory_extraction.py`, `infrastructure/db_models.py`, `infrastructure/repository.py`); `app/main.py` gains an import so the new ORM model registers on `Base.metadata` (mirrors how `recommendation`'s db_models are pulled in via its `wiring.py` import, since this module has no user-facing API router).
- **Database**: new migration adding `conversation_memory`, chained after `0007_sprint2_1_lead_objections`.
- **Tests**: new `tests/test_conversation_memory.py`.
- **Docs**: new `openspec/specs/conversation-memory/spec.md`; `Documents/Oficial/HU_Calificacion_Recomendacion.md` AI-102 gap marker removed once implemented.
- **Downstream**: none yet — this change deliberately has no consumer (US-211, which would read `conversation_memory` to infer an affinity profile, is out of scope per the source HU's own alignment note "(d) ... bloquea a US-211 (fuera de este scope, sub-sprint 2.2)").
