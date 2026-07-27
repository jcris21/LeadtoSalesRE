## Why

`LeadScoringService` (US-209) only produces a binary-ish Hot/Warm/Cold classification driven
exclusively by negative signals (objections eroding a base score of 100). It never rewards positive
qualification signals (budget declared, zone declared, urgent timeline, financing readiness, decision
maker identified). US-214 asks for a second, orthogonal output: a continuous 0-100 weighted score plus
a 3-state financing-readiness classification (READY/PRE-READY/DISCOVERY), so that a lead with strong
partial signals (e.g. financing + timeline + locations, but not all 7 `PROFILE_DIMENSIONS`) can be
recognized as ready before the full profile is complete. `OwnershipPolicyEngine` does not exist in the
codebase yet (grepped, only an unrelated `conversation_ownership/application/ownership_policy.py`), so
this change scopes to producing the score/readiness output only -- no consumer is wired up.

## What Changes

- Add `FinancingReadiness` enum (`READY`/`PRE_READY`/`DISCOVERY`) to
  `app/modules/lead_qualification/domain/models.py`, alongside the existing `LeadClassification`.
- Add a new `LeadReadinessService` in
  `app/modules/lead_qualification/application/lead_readiness.py` with:
  - `compute_readiness_score(profile: BuyerProfile) -> float`: deterministic weighted sum over six
    signals (intent/property_type, budget, zone/locations, timeline, financing_type, decision_maker_mode),
    clamped to [0, 100].
  - `classify_financing_readiness(profile: BuyerProfile) -> FinancingReadiness`: deterministic rule
    based on which of financing_type/timeline/locations is captured.
  - `LeadReadinessService.evaluate(profile) -> LeadReadinessResult`: computes both and persists them.
- Add `buyer_profiles.readiness_score` (Float, nullable) and `buyer_profiles.financing_readiness`
  (String(16), nullable) via a new Alembic migration (`0020_lead_readiness_score.py`).
- Add `BuyerProfileRepository.set_readiness(...)`, an isolated writer mirroring the existing
  `set_ai_profile` pattern (never folded into `save()`, so progressive-profiling writes can never
  clobber it and vice versa).
- **Purely additive**: `LeadScoringService.compute_lead_score`/`classify`/`record_objection`,
  `Lead.lead_score`/`lead_classification`, and every existing objection test remain unchanged.

## Capabilities

### New Capabilities
- `lead-continuous-readiness`: the deterministic continuous readiness score + 3-state financing
  readiness classification, computed from `BuyerProfile` and persisted on `buyer_profiles`.

### Modified Capabilities
- (none) -- `lead-qualification`'s existing Hot/Warm/Cold requirements are untouched; this proposal
  only adds a new, independent capability alongside them.

## Impact

- `app/modules/lead_qualification/domain/models.py` -- new `FinancingReadiness` enum.
- `app/modules/lead_qualification/application/lead_readiness.py` -- new file.
- `app/modules/lead_qualification/infrastructure/db_models.py` -- two new columns on `BuyerProfileORM`.
- `app/modules/lead_qualification/infrastructure/repository.py` -- new `set_readiness` method.
- `alembic/versions/0020_lead_readiness_score.py` -- new migration.
- Tests: `tests/test_lead_readiness_service.py` (new). No changes to
  `tests/test_lead_objections.py`/`lead_scoring.py` behavior.
