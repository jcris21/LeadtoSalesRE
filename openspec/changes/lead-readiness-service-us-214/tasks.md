## 1. Domain

- [x] 1.1 Add `FinancingReadiness` enum (`READY`/`PRE_READY`/`DISCOVERY`) to
      `app/modules/lead_qualification/domain/models.py`, alongside `LeadClassification`.

## 2. LeadReadinessService

- [x] 2.1 Create `app/modules/lead_qualification/application/lead_readiness.py` with
      `compute_readiness_score(profile) -> float` (design.md Decision 1 weight table, clamped to
      [0, 100]).
- [x] 2.2 Add `classify_financing_readiness(profile) -> FinancingReadiness` (design.md Decision 2
      rule).
- [x] 2.3 Add `LeadReadinessResult` dataclass and `LeadReadinessService.evaluate(profile) ->
      LeadReadinessResult`, persisting via `BuyerProfileRepository.set_readiness`.

## 3. Persistence

- [x] 3.1 Add `readiness_score` (Float, nullable) and `financing_readiness` (String(16), nullable)
      columns to `BuyerProfileORM` in `infrastructure/db_models.py`.
- [x] 3.2 Add `BuyerProfileRepository.set_readiness(lead_id, *, readiness_score, financing_readiness)
      -> bool` mirroring `set_ai_profile`'s isolated-writer, no-row-creation pattern.
- [x] 3.3 Create Alembic migration `alembic/versions/0020_lead_readiness_score.py` (`down_revision =
      "0019"`), `upgrade`/`downgrade` for both columns.

## 4. Tests

- [x] 4.1 `tests/test_lead_readiness_service.py`: `compute_readiness_score` for empty profile (0.0),
      the ticket's example scenario (financing_type+timeline+locations, partial profile), and a fully
      captured profile at max tiers (100.0).
- [x] 4.2 Cover all three `classify_financing_readiness` outcomes with at least one case each.
- [x] 4.3 Cover persistence: `evaluate()` writes both columns for an existing `buyer_profiles` row;
      no-op (returns False internally, no exception) when no row exists yet.
- [x] 4.4 Run the full `pytest` suite; confirm `tests/test_lead_objections.py` and every other
      pre-existing test stays green (no behavior change to `LeadScoringService`).

## 5. Documentation

- [x] 5.1 Delta spec `openspec/changes/lead-readiness-service-us-214/specs/lead-qualification/spec.md`
      documenting the new `lead-continuous-readiness` requirements.
