## Why

`BuyerProfile.apply` and `BuyerProfileCaptureService.update_profile` (domain + application layers of
`lead_qualification`) already validate, persist, and emit `ProfileCompleted` for all five progressive
profiling dimensions. But there is no conversational entry point that calls `update_profile` — no
`app/modules/lead_qualification/api/` router, and no Qualification Flow LLM sub-prompt that turns a
lead's WhatsApp message into a `ProfilePatch`. As a result, US-202 (budget), US-203 (locations),
US-204 (property_type), and US-205 (timeline/must_haves) are all stuck at "Parcial" in
`Documents/Oficial/HU_Calificacion_Recomendacion.md` — the deterministic half of the pipeline exists,
the agentic half does not. This change closes that gap for all four dimensions at once, since they
share one root cause and one fix.

## What Changes

- Add `app/modules/lead_qualification/application/qualification_flow.py`: one Prompt Chaining module
  (per `Documents/Oficial/Agentic_System.md` pattern #1) with sub-prompts for `budget`, `locations`,
  `property_type`, and `timeline`/`must_haves` extraction from a lead's message, each producing a
  `ProfilePatch` and calling `BuyerProfileCaptureService.update_profile`.
- Add `app/modules/lead_qualification/api/router.py` exposing support/QA endpoints for each dimension
  (`POST /api/v1/leads/{lead_id}/profile/{budget|locations|property-type|timeline|must-haves}`), used
  for manual testing and as a fallback entry point independent of the LLM flow.
- Register the new router in `app/main.py`.
- Translate `ProfileValidationError` to a conversational re-prompt (or 422 for the REST path) instead
  of letting it reach the user as an unhandled exception.
- Enforce tenant isolation: every write validates the target lead's `organization_id` against the
  authenticated/session context before calling `update_profile`.

## Capabilities

### New Capabilities
- `lead-qualification-flow`: conversational + support-endpoint capture of the four progressive
  profiling dimensions (budget, locations, property_type, timeline/must_haves) into `BuyerProfile`,
  closing the gap between the existing domain/application layers and the conversation.

### Modified Capabilities
- (none — the existing `BuyerProfile`/`update_profile` domain and application behavior is unchanged;
  this change only adds the missing entry point that invokes it.)

## Impact

- **Code**: new files `app/modules/lead_qualification/application/qualification_flow.py`,
  `app/modules/lead_qualification/api/router.py`; edit `app/main.py` to register the router.
- **No schema changes**: `buyer_profiles`/`leads` tables and `BuyerProfileORM` are untouched — this is
  purely a new write path into existing columns (`budget_min/max`, `locations`, `property_type`,
  `timeline`, `must_haves`).
- **Docs**: `Documents/Oficial/HU_Calificacion_Recomendacion.md` rows for US-202–US-205 move from
  "Parcial" to "Implementado" once the conversational entry point lands (not just the support
  endpoints).
- **Dependencies**: none beyond what `lead_qualification` already depends on (SQLAlchemy async session,
  existing `BuyerProfileCaptureService`, `LeadRepository`).
