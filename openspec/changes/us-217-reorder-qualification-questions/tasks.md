## 1. Domain reorder

- [x] 1.1 Reorder `PROFILE_DIMENSIONS` in `app/modules/lead_qualification/domain/models.py`
      to `budget, locations, property_type, timeline, financing_type,
      decision_maker_mode, must_haves, bedrooms`, with a comment referencing US-217 and
      the Nivel 1 / Nivel 2 split.

## 2. Orchestration reorder

- [x] 2.1 Reorder `_DETERMINISTIC_EXTRACTORS` in
      `app/modules/lead_qualification/application/qualification_turn.py` to mirror the
      same Nivel 1 → Nivel 2 precedence, with a comment referencing US-217.

## 3. Tests

- [x] 3.1 Update `test_profile_dimensions_now_has_eight_elements` in
      `tests/test_buyer_profile.py` to assert the new `PROFILE_DIMENSIONS` order.
- [x] 3.2 Add a test proving `CompletenessGate.missing_dimension` returns a Nivel 1
      dimension over a Nivel 2 one when both are missing.
- [x] 3.3 Add a test asserting `_DETERMINISTIC_EXTRACTORS` ordering places
      `extract_bedrooms` after the Nivel 1 extractors (and `extract_budget`'s
      conditional insert still lands ahead of all of them).

## 4. Verification

- [x] 4.1 Run `pytest tests/test_buyer_profile.py tests/test_qualification_flow.py
      tests/test_coordinator_qualification_turn.py -q` and confirm all green.
