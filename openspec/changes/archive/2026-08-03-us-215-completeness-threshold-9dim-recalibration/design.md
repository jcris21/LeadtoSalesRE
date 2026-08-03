## Context

`CompletenessGate` (`app/modules/lead_qualification/application/completeness_gate.py`)
is the single point of truth for the `Qualification -> Recommendation`
transition precondition (QA-14, Architecture.md §7.8/§10 Iter. 3). It reads
its default threshold from `Settings.profile_completeness_threshold`
(`app/core/config.py:46`, currently `80.0`). `BuyerProfileCaptureService`
uses the same setting to decide exactly when to publish `ProfileCompleted`.

`PROFILE_DIMENSIONS` (`app/modules/lead_qualification/domain/models.py`) now
has 9 entries, ordered Nivel 1 (qualification-blocking) before Nivel 2
(refinement) per US-217:

- Nivel 1 (6): `budget`, `locations`, `property_type`, `timeline`,
  `financing_type`, `decision_maker_mode` — exactly the six signals
  `LeadReadinessService` (US-214) weights.
- Nivel 2 (3): `must_haves`, `bedrooms`, `motivation` (the last added by
  US-219, after the original US-215 threshold was calibrated).

`completeness()` = `100 * captured/applicable_total`. With 9 dimensions the
values around the Nivel-1-complete crossing are:

- 5/9 = 55.555...% (one Nivel 1 dimension still missing)
- 6/9 = 66.666...% (all Nivel 1 dimensions captured, zero Nivel 2)

The current `80.0` default requires ~7.2/9 — i.e. all of Nivel 1 plus at
least 2 of the 3 Nivel 2 dimensions — which no longer matches the
"recommendation-first once core signals are known" intent.

## Goals / Non-Goals

**Goals:**
- Recalibrate the platform-default completeness threshold so the gate opens
  exactly when the six Nivel 1 dimensions are captured, under the current
  9-dimension model.
- Keep the recalibration a pure constant change — no new gate logic, no
  change to `PROFILE_DIMENSIONS` or `completeness()`.
- Bring `tests/test_buyer_profile.py` and `tests/test_qualification_flow.py`
  back in line with the 9-dimension model (both already contain assertions
  that predate US-219's `motivation` addition).

**Non-Goals:**
- Changing `PROFILE_DIMENSIONS` membership, order, or `completeness()`'s
  formula.
- Per-organization configurable thresholds (still a single platform-wide
  default, consistent with existing `app/core/config.py` architecture).
- Any change to the Matching/Recommendation pipeline, or to which
  dimensions are Nivel 1 vs Nivel 2.

## Decisions

- **Threshold value: `65.0`.** With `completeness()` producing multiples of
  100/9 (≈11.11) for a 9-dimension profile, `65.0` is the value that:
  - is `<= 66.67` (6/9), so the gate opens as soon as all Nivel 1 dimensions
    are captured, and
  - is `> 55.56` (5/9), so the gate does **not** open one Nivel 1 dimension
    early.
  Any value in `(55.56, 66.67]` satisfies both properties; `65.0` is chosen
  for a comfortable margin below the 6/9 crossing (≈1.67 points) while
  staying well clear of 5/9 (≈9.44 points), matching the style of the
  original US-215 choice of `80.0` as "the tightest correct value" — here
  we favor a round number with margin over the exact boundary (`66.67`)
  since floating-point equality at the boundary is undesirable for a `>=`
  comparison already used by `CompletenessGate`.
- **Change the config default only.** `CompletenessGate` and
  `BuyerProfileCaptureService` already accept an explicit threshold
  override; tests using `CompletenessGate(threshold=90.0)` etc. are
  independent of the default and remain unchanged.
- **Rewrite, don't delete, the crossing-threshold test.**
  `test_profile_completed_fires_exactly_on_crossing_threshold` in
  `tests/test_buyer_profile.py` exercises the real config default. It
  currently assumes the crossing happens at the 9th (last) update, at
  100%. Under `65.0` the event now fires after the 6th update (once
  `decision_maker_mode` — the last Nivel 1 dimension — is captured), at
  ≈66.67%. The test is rewritten to assert exactly that, and to assert the
  three subsequent Nivel 2 updates (`bedrooms`, `motivation`, `must_haves`)
  do not re-publish `ProfileCompleted`.
- **Add an explicit default-threshold gate test.** A new test builds a
  `BuyerProfile` with exactly the 6 Nivel 1 dimensions (no Nivel 2) and
  asserts `CompletenessGate()` (default, config-sourced) returns
  `can_advance=True`; a second builds one with only 5 of 6 Nivel 1
  dimensions and asserts `can_advance=False`. This is the direct proof the
  recalibration took effect.
- **Fix the unrelated but already-broken `test_deterministic_extractors_run_nivel_2_bedrooms_last`.**
  This test predates US-219: it asserts `extract_bedrooms` is the last
  deterministic extractor, but `_DETERMINISTIC_EXTRACTORS` in
  `qualification_turn.py` now ends with `extract_motivation` (added after
  `extract_bedrooms`). It is not caused by this change but is in the same
  test file this change is asked to bring current; it is updated to assert
  `extract_motivation` is last and that both Nivel-2-only extractors
  (`extract_bedrooms`, `extract_motivation`) follow every Nivel 1 extractor.

## Risks / Trade-offs

- [Risk] Some other test or code path silently assumes `80.0`/an
  8-dimension model → Mitigation: grepped the whole repo for
  `profile_completeness_threshold` and `CompletenessGate(` before changing
  anything; all other call sites pass an explicit threshold and are
  independent of the default.
- [Risk] Lowering the threshold further (65.0 vs. 80.0) means Matching now
  runs with even less Nivel 2 information on average → Mitigation: this is
  the same intentional "recommendation-first" trade-off the original
  US-215 already accepted; Nivel 2 dimensions remain asked as follow-up
  refinement (US-217/US-219), unaffected by this change.
- [Trade-off] `65.0` is not the exact crossing boundary (`66.67`); a lead
  with 6/9 dimensions is comfortably above threshold, but this is
  deliberate — using the exact boundary value risks a false negative from
  floating-point rounding in `100.0 * captured / applicable_total`.

## Migration Plan

- Single-line config default change, no schema/data migration, no feature
  flag (platform-level `Settings` field, env-overridable if ever needed).
- Rollback: revert the constant to `80.0` in `app/core/config.py`; no data
  cleanup needed since the gate is a pure read-time predicate.

## Open Questions

- None. Threshold recalibration is fully determined by the current
  `PROFILE_DIMENSIONS` size and the Nivel 1/Nivel 2 split already fixed by
  US-217/US-219.
