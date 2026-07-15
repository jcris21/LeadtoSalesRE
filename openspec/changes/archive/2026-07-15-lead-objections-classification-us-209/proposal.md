## Why

`Lead.lead_score` (`app/modules/lead_qualification/domain/models.py`) exists but nothing in the codebase writes to it today — it is set only by `Lead.mark_synced()` from the wacrm snapshot (a passive mirror value), never computed locally from conversational signal. The Customer Journey requires the AI Agent to classify each lead as Hot/Warm/Cold and to track sales objections (Precio, Zona, Financiamiento, Tamaño, Tiempo) so the commercial team can prioritize follow-up. This is a documented gap (US-209 in `Documents/Oficial/HU_Calificacion_Recomendacion.md`) blocking commercial prioritization on top of the qualification signal US-202-US-208 already capture.

## What Changes

- Add an `Objection` domain entity (`type: ObjectionType`, `raw_text`, `lead_id`, `organization_id`, `created_at`) to `app/modules/lead_qualification/domain/models.py`, with `ObjectionType` enum (`PRECIO`, `ZONA`, `FINANCIAMIENTO`, `TAMANO`, `TIEMPO`).
- Add a deterministic keyword-based objection-detection extractor `extract_objection` in `qualification_flow.py` (Spanish keywords per objection type, consistent with the codebase's existing deterministic-first pattern — no LLM call in this change).
- Add a `LeadScoringService` (or equivalent) that recomputes `Lead.lead_score` and a `LeadClassification` (Hot/Warm/Cold) whenever an objection is recorded, using an explicit weighted rule (base score minus a per-objection penalty, documented in design.md).
- New table `lead_objections` (id, lead_id, organization_id, type, raw_text, created_at) via a new Alembic migration chained after `0006_sprint2_1_buyer_profile_dimensions`.
- Extend `Lead` with a `classification: LeadClassification` derived field (or persisted column — decided in design.md) so downstream consumers (e.g. the Recommendation module, future CRM sync) can read Hot/Warm/Cold without recomputing.
- Repository/persistence wiring for `lead_objections` (`LeadObjectionRepository`).
- **BREAKING (behavioral, not schema)**: `Lead.lead_score` was previously purely a wacrm mirror value (overwritten by every `mark_synced()` call); this change introduces a second, local writer (objection-triggered recompute). design.md documents how the two writers are reconciled so a CRM re-sync doesn't silently erase locally-computed penalties.

## Capabilities

### New Capabilities

(none — this extends the existing `lead-qualification` capability's requirements; objections and classification are new requirements of the same bounded context that already owns `Lead` and `BuyerProfile`, not a new bounded context)

### Modified Capabilities

- `lead-qualification`: `Lead` gains a Hot/Warm/Cold classification derived from `lead_score`; recording an `Objection` triggers a `lead_score`/classification recompute. New sub-requirement: objection detection during Discovery/Recommendation conversation states.

## Impact

- **Code**: `app/modules/lead_qualification/domain/models.py`, `application/qualification_flow.py`, new `application/lead_scoring.py` (or similar), `infrastructure/repository.py`, `infrastructure/db_models.py`.
- **Database**: new migration adding `lead_objections` table, chained after `0006_sprint2_1_buyer_profile_dimensions`.
- **Tests**: new `tests/test_lead_objections.py` (or extend `tests/test_qualification_flow.py` / `tests/test_buyer_profile.py`), covering keyword extraction per objection type and the scoring/classification recompute.
- **Docs**: `openspec/specs/lead-qualification/` gets a delta spec; `Documents/Oficial/HU_Calificacion_Recomendacion.md` US-209 gap marker removed once implemented.
- **Downstream**: `Lead.lead_score`/classification consumers (e.g. commercial dashboards, future CRM sync of score) start seeing locally-influenced values; `LeadSyncAdapter.mark_synced()` behavior around `lead_score` is clarified in design.md so it doesn't fight with the new local writer.
