## Context

`qualification_flow.py` extracts profile dimensions deterministically (regex/keyword), one function
per dimension, each persisting via `BuyerProfileCaptureService.update_profile`. `BuyerProfile`
(`domain/models.py`) tracks 8 dimensions today (`PROFILE_DIMENSIONS`) and `CompletenessGate` uses
`missing_dimensions()` to pick the next directed question. There is no floor/piso dimension in this
codebase — the HU's "no preguntar piso si es casa" example is illustrative of the general pattern
(skip Nivel 2 questions irrelevant to `property_type`), not a literal existing field.

Migration ordering: this worktree's alembic head, verified by walking `down_revision` chains in
`alembic/versions/`, is `0021_knowledge_documents` (US-214's `0020_lead_readiness_score` already
merged, chained under it). The new migration must set `down_revision = "0021"`.

## Goals / Non-Goals

**Goals:**
- Capture buyer motivation (mudanza/inversión/vacacional/primera_vivienda) with the same
  determinism/tenant-isolation guarantees as existing extractors.
- Make "which Nivel 2 question is still missing" property_type-aware, so a lead who already said
  `property_type=LAND` is never asked (or held incomplete for) a dimension that doesn't apply to
  land purchases.
- Keep the change strictly additive: no existing extractor, column, or threshold behavior changes
  for leads that don't have the new column populated.

**Non-Goals:**
- Not introducing a literal "floor/piso" dimension (out of scope; no code today asks about floors).
- Not touching `profile_completeness_threshold` (US-215) or the Hot/Warm/Cold scoring (US-209/214).
- Not adding an LLM call for motivation detection (deterministic-only, consistent with
  `extract_property_type`).

## Decisions

1. **`motivation` becomes a 9th `PROFILE_DIMENSIONS` entry**, not a side-channel field (unlike
   `readiness_score`/`ai_profile`, which are isolated-writer snapshots). Rationale: the HU explicitly
   says "se registra motivation en BuyerProfile (campo nuevo, mismo patrón que budget/timeline)" —
   budget/timeline are `PROFILE_DIMENSIONS` members, so motivation should follow the same contract
   (counts toward `completeness()`, appears in `missing_dimensions()`, settable via `ProfilePatch`).
   Alternative considered: keep it out of `PROFILE_DIMENSIONS` as a purely informational field (like
   `ai_profile`) — rejected because the HU frames it as a captured qualification signal, not a
   derived analytics snapshot.

2. **Adaptive filtering lives in `BuyerProfile.missing_dimensions()`/`completeness()`**, keyed off
   `self.property_type`, via a small lookup table
   `_INAPPLICABLE_DIMENSIONS_BY_PROPERTY_TYPE: dict[PropertyType, frozenset[str]]`. This is the
   single call site every consumer already uses (`CompletenessGate`, the generative-extractor
   fallback in `qualification_turn.py`), so filtering there propagates everywhere for free — no need
   to change `CompletenessGate`'s or the generative extractor's code. `bedrooms` is excluded for
   `LAND` and `COMMERCIAL` (the only existing dimension that is genuinely irrelevant for those two
   property types, serving as this codebase's concrete instance of the HU's "skip piso" example).
   Alternative considered: a separate `next_question_dimension(property_type)` helper distinct from
   `missing_dimensions()` — rejected because it would require every caller to be updated and risks
   the two lists drifting out of sync.
   Edge case: when `property_type` is `None` (not yet captured), no filtering is applied — nothing is
   excluded until we actually know the type.

3. **Migration `down_revision="0021"`**, verified against the actual chain in
   `alembic/versions/*.py` (not copied from the HU doc, which predates several merges). Nullable
   `String(32)` column, no backfill, mirrors `0020_lead_readiness_score`'s additive-column pattern.

## Risks / Trade-offs

- [Risk] A profile that already captured `bedrooms` before `property_type` was corrected to `LAND`
  keeps `bedrooms` in `captured_dimensions()` (stale but harmless) → Mitigation: acceptable, matches
  the "None never erases" invariant already documented for `ProfilePatch`; not in scope to add
  retroactive dimension pruning.
- [Risk] Two branches (this one and a hypothetical parallel US-214-adjacent branch) both adding a
  `buyer_profiles` migration off the same head → Mitigation: this design explicitly re-verifies the
  head via the actual file chain right before creating the migration file, per the HU's documented
  merge-conflict warning.
- [Risk] Motivation keyword false-positives (e.g. "inversión" appearing in an unrelated sentence) →
  Mitigation: same acceptable precision/recall trade-off as existing keyword extractors; not a
  regression since no motivation detection exists today.

## Migration Plan

- Single additive Alembic migration adding `buyer_profiles.motivation` (nullable). No data migration
  needed. `downgrade()` drops the column. Deploys independently of any other in-flight branch since
  it only depends on `0021` being applied.
