## Context

`BuyerProfile.missing_dimensions()` (`app/modules/lead_qualification/domain/models.py`)
filters `PROFILE_DIMENSIONS` by what's not yet captured, preserving the tuple's order.
`CompletenessGate.can_advance_to_recommendation()` uses `missing_dimensions()[0]` as the
directed next question when the profile isn't complete enough to advance to
Recommendation. The current `PROFILE_DIMENSIONS` order is:

```
budget, locations, property_type, timeline, must_haves, financing_type,
decision_maker_mode, bedrooms
```

`must_haves` (Nivel 2 — refinement, e.g. "necesito que tenga cochera") sits ahead of
`financing_type`/`decision_maker_mode`, which are Nivel 1 signals: `LeadReadinessService`
(US-214) weights exactly six signals — intención (`property_type`), presupuesto
(`budget`), zona (`locations`), horizonte (`timeline`), forma de pago (`financing_type`),
decisor (`decision_maker_mode`) — as the readiness/qualification core. `must_haves` and
`bedrooms` are not part of that set; they are refinement details that should not compete
with qualification-blocking questions for "what do we ask next."

`_DETERMINISTIC_EXTRACTORS` in `qualification_turn.py` runs every applicable extractor
against every incoming message regardless of order (each extractor independently pattern
matches its own dimension in the same text), so its order has no effect on *what a single
message extracts* — but keeping it aligned with `PROFILE_DIMENSIONS` keeps the two files
readable as one coherent precedence story for future maintainers (and for US-219, which
will add more Nivel-2-style extractors).

## Goals / Non-Goals

**Goals:**
- Nivel 1 dimensions (`budget`, `locations`, `property_type`, `timeline`,
  `financing_type`, `decision_maker_mode`) always precede Nivel 2 dimensions
  (`must_haves`, `bedrooms`) in `PROFILE_DIMENSIONS`, so `CompletenessGate`'s directed
  question always exhausts Nivel 1 before Nivel 2.
- Mirror the same precedence in `_DETERMINISTIC_EXTRACTORS` for readability.
- Zero behavior change to `BuyerProfile.completeness()`'s percentage (still `count /
  len(PROFILE_DIMENSIONS)`, order-independent) — US-215's threshold recalibration is a
  separate, independently-configured change.

**Non-Goals:**
- Splitting `extract_timeline_and_must_haves` into two extractors (would be new domain
  logic; out of scope per the HU's own alignment note).
- Changing `profile_completeness_threshold` (US-215).
- Touching `coordinator.py` or the Identity Gate (US-218).
- Adding new `BuyerProfile` fields or a migration.

## Decisions

1. **Reorder `PROFILE_DIMENSIONS` only, not `captured_dimensions()`'s internal if-chain.**
   `missing_dimensions()` computes `tuple(d for d in PROFILE_DIMENSIONS if d not in
   captured)` — order comes solely from `PROFILE_DIMENSIONS`, so reordering the if-chain
   in `captured_dimensions()` is cosmetic and would widen the diff without changing
   behavior. Left untouched to keep the change minimal and merge-safe.
2. **financing_type/decision_maker_mode are classified as Nivel 1, not Nivel 2.**
   Alternative considered: treat them as their own "Nivel 1.5" between the HU's named
   Nivel 1 fields and Nivel 2 — rejected because the HU's Nivel 1/Nivel 2 split is
   business-intent-based ("intención, tipo, ubicación, presupuesto, horizonte" vs
   "dormitorios, amenidades, mascotas, piso"), and financing/decision-maker map onto
   qualification-blocking readiness signals (US-214), not amenity-style refinement.
3. **No coordinator.py change.** Confirmed via grep that `coordinator.py` does not read
   `GateResult.missing_dimension` or `PROFILE_DIMENSIONS` directly (only
   `recommendation_service.py` and `generative_extractor.py` do, and neither is
   order-sensitive beyond consuming the tuple as a set). Keeps the diff out of the
   US-218 Identity Gate merge-conflict zone.

## Risks / Trade-offs

- [Risk] Existing tests hardcode the current `PROFILE_DIMENSIONS` tuple order (e.g.
  `test_profile_dimensions_now_has_eight_elements`) → Mitigation: update those
  assertions as part of this change; they are the intended target of the reorder.
- [Risk] Reordering could be perceived as touching "domain logic" → Mitigation: the tuple
  is a `tuple[str, ...]` of field names; no field's type, validation, or persistence
  changes, only its position in the ordered gate/extractor sequence.

## Migration Plan

Pure code change, no data migration. Deploy alongside normal test suite run
(`pytest tests/test_buyer_profile.py tests/test_qualification_flow.py -q`). Rollback is a
plain revert (no schema/state to unwind).

## Open Questions

None — scope is fully bounded by existing extractors/dimensions.
