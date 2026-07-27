## Context

`LeadScoringService` (`app/modules/lead_qualification/application/lead_scoring.py`) computes
`lead_score`/`lead_classification` purely from negative signals (objections). US-214 asks for a
second, positive-signal score, continuous rather than 3-bucket, plus a separate financing-readiness
tri-state. `BuyerProfile` (`app/modules/lead_qualification/domain/models.py`) already has 8 progressive
dimensions (`PROFILE_DIMENSIONS`); the ticket names six signals (intencion, presupuesto, zona,
horizonte, forma de pago, decisor) that must be mapped onto existing fields rather than inventing new
ones.

## Goals / Non-Goals

**Goals:**
- A deterministic (no LLM), reproducible continuous score in [0, 100] driven by the six named signals.
- A deterministic 3-state financing-readiness classification.
- Zero behavior change to `LeadScoringService`/`Lead.lead_score`/`lead_classification`.
- Persist both outputs on `buyer_profiles`, following the `ai_profile`/`set_ai_profile` precedent
  (isolated writer, not part of `BuyerProfileRepository.save`).

**Non-Goals:**
- Wiring into `CoordinatorAgent` or any conversational trigger (that's US-215, not scoped here --
  this ticket only produces the score/readiness output).
- `OwnershipPolicyEngine` integration -- does not exist in the codebase (grepped: only
  `conversation_ownership/application/ownership_policy.py`, an unrelated conversation-assignment
  engine). Not fabricated here.
- Adding `must_haves`/`bedrooms` as scored signals -- the ticket names exactly six dimensions
  (intencion, presupuesto, zona, horizonte, forma de pago, decisor); `must_haves`/`bedrooms` stay out
  of the formula to keep it a direct, auditable mapping to the ticket's Gherkin.

## Decisions

### Decision 1: Six-signal weighted score, mapped onto existing `BuyerProfile` fields

The ticket names six signals that don't map 1:1 to `PROFILE_DIMENSIONS` naming. Mapping chosen:

| Ticket signal | `BuyerProfile` field         | Max weight | Rationale |
|----------------|------------------------------|-----------:|-----------|
| intencion      | `property_type` captured     | 15         | What the buyer intends to purchase is the closest existing field to "intent". |
| presupuesto    | `budget` captured            | 20         | Budget is the single strongest qualification signal (drives inventory match); weighted highest among binary-captured signals. |
| zona           | `locations` captured         | 15         | Needed to narrow inventory, but less discriminating than budget alone. |
| horizonte      | `timeline`, urgency-scaled   | 20 (max)   | Directly encodes urgency, the ticket's second named axis alongside the score itself. |
| forma de pago  | `financing_type`, readiness-scaled | 20 (max) | Directly encodes ability to transact -- the strongest predictor of `financing_readiness` too. |
| decisor        | `decision_maker_mode` captured | 10       | Confirms who must agree, but doesn't itself indicate urgency or ability to pay -- lowest weight. |

Total when every signal is captured at its maximum tier: 15+20+15+20+20+10 = 100.

`timeline` and `financing_type` are **tier-scaled** rather than flat-captured, because the ticket's
title explicitly calls out "urgencia" as a first-class axis, not just "captured or not":

```
Timeline.IMMEDIATE        -> 20   FinancingType.CASH               -> 20
Timeline.THREE_MONTHS     -> 15   FinancingType.MORTGAGE_APPROVED  -> 20
Timeline.SIX_MONTHS       -> 10   FinancingType.MORTGAGE_PREAPPROVED -> 15
Timeline.OVER_SIX_MONTHS  -> 5    FinancingType.EVALUATING         -> 8
Timeline.EXPLORING        -> 2
```

`compute_readiness_score` sums the captured signals' contributions and clamps to `[0, 100]` (the
clamp is a defensive no-op given the weights already sum to exactly 100, but mirrors
`compute_lead_score`'s `max(0.0, ...)` floor style for consistency and future-proofing if weights are
retuned).

### Decision 2: `financing_readiness` 3-state rule

- **READY**: `financing_type` in `{CASH, MORTGAGE_APPROVED}` (already has money or approved credit)
  AND `timeline` in `{IMMEDIATE, THREE_MONTHS}` (urgent) AND `locations` captured (knows where to buy).
  All three conditions must hold -- READY means "could transact now with a matched property".
- **PRE_READY**: `financing_type` is captured (any of the four values, including
  `MORTGAGE_PREAPPROVED`/`EVALUATING`) AND at least one of `timeline`/`locations` is also captured.
  Partial signal: knows how they'll pay, and has started narrowing scope, but doesn't meet the full
  READY bar.
- **DISCOVERY**: everything else -- `financing_type` not yet captured, or captured alone with no
  supporting `timeline`/`locations` signal. Matches the ticket's framing of DISCOVERY as "still
  figuring out the basics".

This directly satisfies the ticket's example scenario: a profile with `financing_type`, `timeline`,
and `locations` captured (not all 7 dimensions) should read as more than "still discovering" --
depending on the exact `financing_type`/`timeline` values it lands on READY or PRE_READY, never
DISCOVERY, matching the Gherkin's intent even though `property_type`/`must_haves`/
`decision_maker_mode`/`bedrooms` are still missing.

### Decision 3: Persist via an isolated `set_readiness` writer, not folded into `save()`

`BuyerProfileRepository.save()` is called by `BuyerProfileCaptureService.update_profile` on every
progressive-profiling patch. If `readiness_score`/`financing_readiness` were written there too,
`LeadReadinessService.evaluate` would need to run on every single patch to avoid the columns going
stale, entangling two independently-triggered computations. Instead, `set_readiness` follows the exact
precedent of `set_ai_profile` (US-211): a narrow method that touches only its own two columns, callable
whenever `evaluate()` runs, independent of the progressive-profiling write path. Returns `False`
(no-op) when the lead has no `buyer_profiles` row yet, same graceful-degradation contract as
`set_ai_profile`.

### Decision 4: `readiness_score`/`financing_readiness` are not added to the `BuyerProfile` domain
entity

Same precedent as `ai_profile`: derived/computed fields that are outputs of a service, not inputs to
progressive profiling, stay off the core entity and its `_to_domain` hydration. `LeadReadinessResult`
is the return value callers use directly; the ORM columns exist purely for persistence/read-back by
future consumers (US-215, a support endpoint, etc.).

## Risks / Trade-offs

- [Risk] The intencion -> `property_type` mapping is a judgment call not spelled out in the ticket
  -> Mitigation: documented explicitly here and in the enriched ticket; `property_type` is the closest
  existing field and keeps the formula additive/auditable without inventing a new dimension.
- [Risk] Weights are a first-pass guess, not derived from real conversion data -> Mitigation: isolated
  as named module constants (`_INTENT_WEIGHT`, `_TIMELINE_WEIGHTS`, etc.), same tunable-constant style
  as `_PENALTY_PER_DISTINCT_TYPE`/`_HOT_THRESHOLD`, so retuning later doesn't require touching the
  formula's structure.
- [Trade-off] No consumer wired (Coordinator/OwnershipPolicyEngine) -- accepted per ticket alignment
  note (d) and the explicit non-goal; wiring is future work (US-215) once `OwnershipPolicyEngine`
  exists.
