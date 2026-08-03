## Context

Post-US-217, `PROFILE_DIMENSIONS` orders `budget, locations, property_type, timeline,
financing_type, decision_maker_mode` (Nivel 1, blocks `CompletenessGate` at the 65%
threshold from US-215) ahead of `must_haves, bedrooms, motivation` (Nivel 2). That split
was justified by `LeadReadinessService`'s (US-214) six weighted signals, not by what the
search pipeline (`hybrid-retrieval`: `StructuredFilterService` + `SemanticRetrievalService`
+ `RankingEngine`) actually consumes. Today `StructuredFilterService.filter_candidates`
(`retrieval.py`) only filters on `budget`/`locations`/`property_type`; `must_haves` already
feeds `SemanticRetrievalService`'s pgvector similarity scoring; `bedrooms` and `motivation`
are captured but never used by search or ranking; `timeline`/`financing_type`/
`decision_maker_mode` are captured but consumed only by `LeadReadinessService`, not by
search at all.

This change re-derives Nivel 1/Nivel 2 from "does the search pipeline need this to find
the right properties" instead of "does `LeadReadinessService` weight this", and adds a
genuinely new deterministic follow-up turn to ask for the sales-relevant Nivel 2 signals
once the lead has committed interest to a specific property.

## Goals / Non-Goals

**Goals:**
- Nivel 1 = `budget, locations, property_type, bedrooms, motivation, must_haves` blocks
  the recommendation (same 65%-of-9 completeness mechanics as today, over the new set).
- `bedrooms` becomes a real SQL hard filter, on par with budget/locations/property_type.
- `must_haves` keeps refining the semantic-similarity stage exactly as it does today —
  only its `PROFILE_DIMENSIONS` position changes.
- Nivel 2 (`timeline, financing_type, decision_maker_mode`) is asked by a new deterministic
  follow-up turn, gated on the lead having selected a specific Top-3 property
  (`RecommendationORM.feedback` marker from US-220's `mark_selected`), never blocking
  scheduling.
- `LeadReadinessService.compute_readiness_score` weights are remapped to the new Nivel 1
  set; `classify_financing_readiness` is untouched.

**Non-Goals:**
- No rename of `must_haves` to any other identifier (field, column, API key, extractor
  name) — out of scope by explicit user decision.
- No change to `CompletenessGate`'s threshold, its `missing_dimensions()[0]`-driven
  directed-question mechanism, or `profile_completeness_threshold` (US-215).
- No change to `must_haves`'/`bedrooms`' *semantic* extraction logic (regex/keyword
  matching) beyond splitting the extractor function that currently bundles
  `must_haves` with `timeline`.
- No bedrooms *range* filtering (e.g. "3+ habitaciones") — exact-match only, matching the
  precedent set by `property_type`/`zone` equality filters. Range semantics are a future
  enhancement if a lead ever expresses "al menos 3".
- No LLM involvement in the new follow-up turn — deterministic text, same posture as
  `deepening_turn.py`/`scheduling_turn.py`.

## Decisions

### D1: `properties.bedrooms` needs a new column + migration
`Property`/`PropertyORM` never modeled bedrooms — only `BuyerProfile.bedrooms` exists
today. Adding it as a hard filter therefore requires:
- `alembic/versions/xxxx_properties_bedrooms.py`: `properties.bedrooms` — nullable
  `Integer`, no default, no backfill (existing rows keep `NULL`; a `NULL` row is excluded
  the moment any lead specifies a bedroom count, same "absent value never matches a
  present constraint" posture `matches_hard_filters` already uses for the other fields —
  the alternative of defaulting to 0 would make untagged inventory permanently invisible
  to any bedroom-filtered search, which is worse).
- `Property.__init__` gains `bedrooms: int | None = None`; `matches_hard_filters` gains a
  `bedrooms: int | None` parameter with the same "`None` constraint = no clause, `None`
  property value = excluded once a constraint is present" logic as the existing fields.
- `PropertyLookup.filter_candidates` Protocol and `StructuredFilterService.filter_candidates`
  thread `buyer_profile.bedrooms` through to the store call.
- `PropertyRepository.filter_candidates` (`infrastructure/repository.py`) adds
  `query.where(PropertyORM.bedrooms == bedrooms)` when `bedrooms is not None`, mirroring
  the existing `property_type` clause at line 126.

Alternative considered: keep `bedrooms` as a post-filter ranking signal only (no SQL
clause), avoiding the migration. Rejected — the user explicitly asked for a **hard**
filter, and `RankingEngine` scores already-filtered candidates, so a signal-only approach
would still show properties with the wrong bedroom count, just ranked lower.

### D2: Split `extract_timeline_and_must_haves` into two extractors
The combined extractor exists because US-217 explicitly kept timeline+must_haves as one
call ("splitting timeline from must_haves would be new domain logic, out of scope"). Now
that `timeline` is Nivel 2 and `must_haves` is Nivel 1, that shared precedence is wrong —
`_DETERMINISTIC_EXTRACTORS` needs to run `extract_must_haves` in the Nivel 1 block and
`extract_timeline` in the Nivel 2 block. Split into `extract_timeline` and
`extract_must_haves`, each returning `ProfilePatch | str | None` exactly as the combined
version does today; both keep their existing regex/keyword bodies verbatim (pure
extraction-worthy split, no detection-logic change).

### D3: New follow-up turn checks persisted selection state, not just this turn's transition
`deepening_turn.run_deepening_turn` returns `outcome == "selected"` only on the turn where
the lead's message resolves the pick; every later turn in `RECOMMENDATION` returns
`"not_applicable"` (`any(is_lead_selected(row) ...)` short-circuit). A follow-up turn that
only fires on the exact "selected" turn would miss every subsequent message. Instead, the
new turn (module `followup_turn.py`, sibling to `deepening_turn.py`) independently checks
`RecommendationRepository.list_for_lead` + `is_lead_selected` for the latest batch:
- Not applicable: no recommendations yet, or nothing selected yet (deepening owns that
  gap), or the profile's Nivel 2 dimensions are already all captured.
- Applicable: the latest batch has a lead-selected property AND
  `BuyerProfile.missing_dimensions()` (filtered to `{timeline, financing_type,
  decision_maker_mode}`) is non-empty → returns a directed question for the first missing
  one, same phrasing style as `CompletenessGate`'s existing directed questions.

Alternative considered: react only inline to the exact `deepening.outcome == "selected"`
transition in `coordinator.py`. Rejected — it would silently stop asking on every later
turn, defeating "follow-up", and would duplicate `is_lead_selected` polling logic that
`deepening_turn.py` already owns.

### D4: Turn ordering in `coordinator._conversational_turn`
Insert the new follow-up-turn check immediately after the existing `_deepening_turn` call
(coordinator.py:401-417) and before `_scheduling_turn` (line 418), with the same
short-circuit shape: if the follow-up turn returns a question, reply with it and return
immediately, skipping the LLM responder and scheduling for that turn. Skip it entirely
whenever `_deepening_turn` itself already produced an `"asked"` response this turn (the
Top-3 disambiguation question always wins) — same additive, mutually-exclusive precedence
`_scheduling_turn`/DNI-nudge already follow. Because `run_qualification_turn` still runs
unconditionally every message (unchanged), a lead volunteering `timeline`/
`financing_type`/`decision_maker_mode` before being asked is still captured immediately —
the new turn only asks when nothing was captured passively.

### D5: `LeadReadinessService.compute_readiness_score` reweight
New weight table over the new Nivel 1 set, summing to 100 (same additive-flat-capture
shape as today for `property_type`/`budget`/`locations`, tier tables for anything with
graded values):
- `property_type` (intención): 15
- `budget` (presupuesto): 20
- `locations` (zona): 15
- `bedrooms`: 15 (flat-captured — no natural urgency/tiering, same shape as
  `property_type`/`locations`)
- `motivation`: 15 (flat-captured; `Motivation` has no ordinal "strength" the way
  `Timeline`/`FinancingType` do)
- `must_haves`: 20 (flat-captured; weighted highest of the new additions since it's the
  dimension that most directly shapes which properties get recommended)

`classify_financing_readiness` is left byte-for-byte unchanged: it is a financing-specific
signal (cash/mortgage + urgency + zone), independently meaningful regardless of which
dimensions gate the completeness threshold — explicitly confirmed with the user.

## Risks / Trade-offs

- [Existing `properties` rows have `bedrooms = NULL`] → any lead who specifies a bedroom
  count gets zero matches until inventory is backfilled. Mitigation: ship the migration
  and column first, backfill `properties.bedrooms` from source inventory data as a
  separate, non-blocking data task; `matches_hard_filters` degrades gracefully (empty
  result, not an error) in the meantime, same as any other real filter mismatch today.
- [Splitting `extract_timeline_and_must_haves`] → risk of subtly changing which patch
  wins when a single message carries both signals (today one `ProfilePatch` carries both;
  after the split, two `ProfilePatch` objects go through `BuyerProfileCaptureService`
  sequentially). Mitigation: `ProfilePatch.apply` is additive per-field, so two patches
  from the same message produce an identical end state to one combined patch — verified
  by a new test asserting both split extractors fire independently and non-destructively
  when a message carries both timeline and must_haves language.
- [New follow-up turn adds a third deterministic turn to check every message in
  `RECOMMENDATION`] → extra `RecommendationRepository` query per turn. Mitigation: same
  cost profile as `_deepening_turn`'s existing `list_for_lead` call it must also make;
  no new query pattern, negligible marginal cost.
- [Readiness score reweight changes `LeadReadinessResult.readiness_score` values for every
  existing lead] → any dashboard/report reading historical readiness scores sees a
  discontinuity at deploy time. Mitigation: `readiness_score` is recomputed on every
  `evaluate()` call (no historical snapshot persisted beyond the latest value on
  `buyer_profiles`), so this is a one-time semantic shift, not a data-integrity issue —
  called out in the release notes for whoever owns Hot/Warm/Cold dashboards.

## Migration Plan

1. Alembic migration for `properties.bedrooms` (nullable, no backfill) — additive, zero
   downtime, safe to deploy independently of the rest of this change.
2. Domain/application code changes (extractor split, `PROFILE_DIMENSIONS` reorder,
   `matches_hard_filters`, `LeadReadinessService` reweight) deploy together — they are
   mutually dependent (e.g. `missing_dimensions()` ordering assumptions in tests).
3. New follow-up turn ships in the same deploy — depends on the reordered
   `PROFILE_DIMENSIONS` to know which dimensions are "Nivel 2" (filtered set is a literal
   `{"timeline", "financing_type", "decision_maker_mode"}` constant in the new module, not
   derived from `PROFILE_DIMENSIONS` slicing, to avoid coupling the turn's behavior to
   tuple order).
4. Rollback: revert the code deploy; the `bedrooms` column is additive and can stay
   (no down-migration needed) even if the rest of the change is rolled back — no other
   code path reads it besides `matches_hard_filters`.

## Open Questions

- Should `bedrooms` matching be exact (`==`) or `>=` ("al menos N habitaciones")? This
  design assumes exact-match for parity with existing `property_type`/`zone` filters;
  confirm during `/opsx:apply` if product wants `>=` semantics instead (changes only the
  SQL clause in `PropertyRepository.filter_candidates`, not the migration or domain shape).
- Inventory backfill for `properties.bedrooms` on existing rows is out of this change's
  scope (application-code only) — needs a follow-up data task before the hard filter is
  useful for the current catalog.
