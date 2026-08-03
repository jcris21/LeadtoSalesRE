## Why

Discovery-stage conversations today ask every lead the same fixed set of Nivel 2 questions
regardless of `property_type`, and never capture *why* the lead is buying (mudanza, inversión,
vacacional, primera vivienda). This makes the conversation feel like a rigid form and wastes turns
on irrelevant questions (e.g. bedroom count for a land/commercial buyer). US-219
(`Documents/Oficial/HU_Calificacion_Recomendacion.md` lines 937-960) asks for a new
`extract_motivation` extractor plus `property_type`-aware filtering of which Nivel 2 dimensions are
still "missing" for a given profile.

## What Changes

- Add a new deterministic extractor `extract_motivation` (keyword/regex, same pattern as
  `extract_property_type`) detecting one of: mudanza (relocation), inversión (investment),
  vacacional (vacation), primera vivienda (first_home).
- Add `motivation` as a 9th `BuyerProfile` dimension (`PROFILE_DIMENSIONS`), following the same
  `ProfilePatch`/`apply`/`captured_dimensions` pattern as `timeline`/`financing_type`.
- Add a `buyer_profiles.motivation` nullable column via a new additive Alembic migration chained
  after the current head.
- Add property-type-aware adaptive filtering: `BuyerProfile.missing_dimensions()`/`completeness()`
  exclude dimensions that do not apply to the lead's `property_type` (e.g. `bedrooms` does not apply
  to `LAND`/`COMMERCIAL` — the closest existing Nivel 2 dimension to the HU's "no preguntar piso si
  es casa" example, since this repo does not model a separate "floor" dimension).
- Wire `extract_motivation` into `run_qualification_turn`'s deterministic extractor list.

## Capabilities

### New Capabilities

(none — this extends the existing qualification flow capability, no new bounded capability)

### Modified Capabilities

- `lead-qualification-flow`: adds the `motivation` dimension/extractor and adaptive
  (`property_type`-aware) missing-dimension/completeness computation.

## Impact

- `app/modules/lead_qualification/domain/models.py` — new `Motivation` enum, `PROFILE_DIMENSIONS`
  extension, adaptive `missing_dimensions()`/`completeness()`.
- `app/modules/lead_qualification/application/qualification_flow.py` — new `extract_motivation`.
- `app/modules/lead_qualification/application/qualification_turn.py` — wiring.
- `app/modules/lead_qualification/infrastructure/db_models.py` — new `motivation` column.
- `app/modules/lead_qualification/infrastructure/repository.py` — map `motivation` both ways.
- `alembic/versions/00XX_us219_buyer_profile_motivation.py` — new additive migration.
- Tests: `tests/test_qualification_flow.py`, `tests/test_coordinator_qualification_turn.py`, plus a
  new migration upgrade/downgrade test.
- No API contract changes, no breaking changes, additive only.
