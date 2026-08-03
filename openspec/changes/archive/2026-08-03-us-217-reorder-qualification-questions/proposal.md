## Why

`CompletenessGate.can_advance_to_recommendation()` asks the lead about `BuyerProfile`'s
first missing dimension, in the order defined by `PROFILE_DIMENSIONS`. Today that order
places `must_haves` (a Nivel 2 refinement signal) ahead of `financing_type` and
`decision_maker_mode` — two Nivel 1 signals that map directly onto two of
`LeadReadinessService`'s (US-214) six readiness weights ("forma de pago", "decisor").
This means a lead can be asked a refinement question (must-have amenities) before all
blocking qualification signals are collected, slowing the path to the US-215 completeness
threshold and to `GeminiRecommendationNarrator.narrate`. US-217 reorders the existing
dimension/extractor precedence — no new extractors, no new domain fields, no migration.

## What Changes

- Reorder `PROFILE_DIMENSIONS` (`app/modules/lead_qualification/domain/models.py`) so all
  six Nivel 1 signals (`budget`, `locations`, `property_type`, `timeline`, `financing_type`,
  `decision_maker_mode`) precede the two Nivel 2 refinement signals (`must_haves`,
  `bedrooms`). This directly reorders `BuyerProfile.missing_dimensions()` and therefore the
  directed question `CompletenessGate` returns.
- Reorder `_DETERMINISTIC_EXTRACTORS` in
  `app/modules/lead_qualification/application/qualification_turn.py` to mirror the same
  Nivel 1 → Nivel 2 precedence, with a comment referencing US-217.
- No changes to `coordinator.py` (confirmed it does not consume `missing_dimension`
  directly) — keeps this change out of the US-218 Identity Gate merge-conflict zone.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `lead-qualification-flow`: adds a requirement that Nivel 1 dimensions are always
  reported as missing/directed-question-worthy before Nivel 2 refinement dimensions.

## Impact

- Affected code: `app/modules/lead_qualification/domain/models.py`,
  `app/modules/lead_qualification/application/qualification_turn.py`.
- Affected tests: `tests/test_buyer_profile.py`, and a new/updated ordering test in
  `tests/test_qualification_flow.py` or a qualification-turn test file.
- No DB migration, no API contract change, no new dependencies.
