## Why

`BuyerProfile` currently captures 5 dimensions (`budget, locations, property_type, timeline, must_haves`) but the documented Customer Journey requires financing type and decision-maker mode to properly qualify a lead and prioritize commercial follow-up. This is a documented gap (US-208 in `Documents/Oficial/HU_Calificacion_Recomendacion.md`) blocking accurate qualification signal for the Recommendation Engine and downstream Hot/Warm/Cold classification (US-209).

## What Changes

- Add `FinancingType` enum (`CASH`, `MORTGAGE_APPROVED`, `MORTGAGE_PREAPPROVED`, `EVALUATING`) and `DecisionMakerMode` enum (`SOLO`, `COUPLE`, `FAMILY`) to the domain model.
- Extend `PROFILE_DIMENSIONS` from 5 to 7 elements, adding `financing_type` and `decision_maker_mode`.
- Extend `ProfilePatch` and `BuyerProfile` with the two new nullable fields, following the existing "`None` = not part of this patch" convention.
- Add a new deterministic keyword extractor `extract_financing_and_decision_mode` in `qualification_flow.py`, mirroring the pattern used by `extract_property_type` / `_TIMELINE_KEYWORDS`.
- Extend `BuyerProfileCaptureService._snapshot()` to include the two new fields in the `ProfileCompleted` event payload.
- Add Alembic migration `0006_sprint2_1_buyer_profile_dimensions` adding nullable `financing_type` and `decision_maker_mode` columns to `buyer_profiles`.
- Extend `BuyerProfileRepository` to persist/read the new columns.
- **BREAKING (behavioral, not schema)**: extending `PROFILE_DIMENSIONS` from 5 to 7 changes the denominator of `BuyerProfile.completeness()`, lowering the relative completeness % of any in-progress profile that hasn't captured the two new dimensions. This affects the QA-14 completeness gate timing. Documented and evaluated in design.md.

## Capabilities

### New Capabilities

(none — this extends the existing `lead-qualification` capability's requirements, no new bounded capability is introduced)

### Modified Capabilities

- `lead-qualification`: `BuyerProfile` completeness now requires 7 dimensions instead of 5; adds `financing_type` and `decision_maker_mode` as first-class profile dimensions captured via conversational extraction.

## Impact

- **Code**: `app/modules/lead_qualification/domain/models.py`, `application/qualification_flow.py`, `application/profile_capture.py`, `infrastructure/repository.py`, `api/schemas.py` (if profile is exposed in a response schema).
- **Database**: new migration `0006_sprint2_1_buyer_profile_dimensions.py` adding two nullable columns to `buyer_profiles`.
- **Tests**: `tests/test_qualification_flow.py`, `tests/test_buyer_profile.py`.
- **Docs**: `openspec/specs/lead-qualification/` gets a delta spec; `Documents/Oficial/HU_Calificacion_Recomendacion.md` US-208 gap marker removed once implemented.
- **Downstream**: no consumer breaks since new fields are nullable and additive; `ProfileCompleted` event payload gains two keys, additive for any consumer using a permissive parser.
