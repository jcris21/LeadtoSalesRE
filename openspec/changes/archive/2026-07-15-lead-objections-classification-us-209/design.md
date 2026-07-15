## Context

`Lead` (`app/modules/lead_qualification/domain/models.py`) already carries a `lead_score: float` field, but the only writer today is `Lead.mark_synced()`, which overwrites it with whatever wacrm reports on each CDC sync — it is a passive mirror, never computed locally. US-209 requires the AI Agent to detect sales objections during Discovery/Recommendation and classify the lead Hot/Warm/Cold to prioritize commercial follow-up. Objections have no existing table; `lead_objections` is a new concept. Extraction in this codebase is deterministic keyword matching (`qualification_flow.py`), no LLM wired yet — this change follows the same pattern; an LLM-backed Objection Handler (per the source HU's "Alineación (b)") is future scope, design-only, zero code here.

## Goals / Non-Goals

**Goals:**
- Detect objections (Precio, Zona, Financiamiento, Tamaño, Tiempo) from lead free text via deterministic Spanish keyword matching, consistent with `extract_budget`/`extract_property_type`/etc.
- Persist each detected objection as its own row in a new `lead_objections` table (append-only log, not a mutable single value — a lead can raise the same objection type more than once, and the sales team wants the history).
- Recompute `Lead.lead_score` and derive a `Hot`/`Warm`/`Cold` classification whenever an objection is recorded, using an explicit, documented rule.
- Keep tenant isolation (`_assert_tenant`) and the `ProfilePatch`-free style consistent with the rest of `qualification_flow.py` (objections are not a `BuyerProfile` dimension, so they do NOT go through `ProfilePatch`/`PROFILE_DIMENSIONS`).

**Non-Goals:**
- No LLM-backed Objection Handler (RAG-based nuance detection) — out of scope, keyword-first cut only, per Sprint 2's established deterministic-first pattern.
- No change to `BuyerProfile`/`PROFILE_DIMENSIONS` — objections are a distinct concept per the source HU ("Alineación (a): transversal... registro de objeciones").
- No wacrm push of `lead_score`/classification in this change — local-only signal for now, same non-goal posture as US-208's financing/decision-mode fields; a future story can wire this into `LeadSyncAdapter` if the commercial team wants it CRM-visible.

## Decisions

**Decision 1 — Hot/Warm/Cold scoring rule: base score minus objection penalty, explicit thresholds.**

`Lead.lead_score` is a 0-100 float. Rule, applied every time an objection is recorded for a lead:

```
lead_score = max(0.0, 100.0 - (unique_objection_types_raised * 15.0) - (total_objections_raised * 5.0))
```

Where `unique_objection_types_raised` is the count of distinct `ObjectionType` values ever recorded for the lead (capped conceptually at 5, since there are only 5 types), and `total_objections_raised` is the total row count in `lead_objections` for the lead (repeated objections of the same type still erode score, since a lead who raises the price objection three times is more resistant than one who raises it once).

Classification thresholds:
- `lead_score >= 70.0` → **Hot**
- `40.0 <= lead_score < 70.0` → **Warm**
- `lead_score < 40.0` → **Cold**

Rationale: a lead starts at the neutral ceiling (100.0, i.e. Hot) before any objection is observed — objections are the only currently-modeled signal that erodes score in this change (positive signals like profile completeness already gate `Qualified` separately via `CompletenessGate`, so this rule intentionally does not double-count that). The dual per-type + per-occurrence penalty means one objection type alone (e.g. only Precio, raised once) drops a lead from 100 to 80 (still Hot), but a lead who raises 3 distinct objection types drops to 55 (Warm), and one who raises 4+ types or repeats objections heavily drops into Cold. This is a first-cut heuristic, deliberately simple and fully deterministic so it's auditable; **flagged as an explicit "needs product/sales review" open question** since the exact weights (15.0 / 5.0) and thresholds (70/40) are not sourced from a documented business rule — they are the implementer's best-effort default consistent with "a few real objections should meaningfully downgrade the lead but not everyone who has any friction should be instantly Cold."

Alternative considered: score as a pure function of objection *count* only (no per-type distinction). Rejected — conflates "raised the same concern twice while still engaged" with "raised concerns across every dimension," which the sales team cares about differently (breadth of resistance vs. depth on one point).

Alternative considered: decay/recency weighting (older objections count less). Rejected for this first cut — adds complexity (needs a time-decay function, config) with no stated requirement; can be a follow-up once the flat rule proves too coarse in practice.

**Decision 2 — `lead_objections` is an append-only log, not a `Lead` sub-object with in-memory list.**

Each detected objection is inserted as its own row (`id, lead_id, organization_id, type, raw_text, created_at`), never updated/deleted. The `Lead` aggregate does not eagerly load its objections (avoids N+1 / always-loaded association); `LeadObjectionRepository.list_for_lead(lead_id)` is a separate query, and the scoring recompute reads directly from the repository (count query), not through the `Lead` entity's in-memory state — mirroring how `CRMAccessAuditRepository` is a parallel audit-style log next to `Lead`, not a field on it.

**Decision 3 — Classification is a derived value stored on `Lead`, recomputed synchronously in the same transaction as the objection insert.**

Add `Lead.lead_classification: LeadClassification` (enum `HOT`/`WARM`/`COLD`, StrEnum matching the `PipelineStage` pattern) as a persisted column (nullable, defaults to `HOT` at Lead creation — a fresh lead with no objections has no negative signal yet). Recomputing synchronously (not via an async event/job) keeps the read-after-write guarantee simple and matches `BuyerProfileCaptureService.update_profile`'s synchronous-recompute style; no new event type is introduced for this change (an `ObjectionRecorded` domain event is emitted for future consumers per Decision 4, but the classification write itself is not deferred to that event's handler).

**Decision 4 — Emit `ObjectionRecorded` domain event (mirrors `ProfileCompleted`) even though nothing consumes it yet.**

Consistent with the existing outbox/event-bus pattern (`ProfileCompleted`, `CRMStageSynced`), recording an objection publishes `ObjectionRecorded{lead_id, crm_lead_id, objection_type, lead_score, lead_classification}` via `event_bus.publish`. No consumer is wired in this change (future: notify assigned broker on Hot→Cold transitions, or push classification to wacrm) — the event exists so that future work doesn't need a second migration/wiring pass through this code path.

**Decision 5 — Objection keyword tables, one per `ObjectionType`, Spanish, single extractor function `extract_objection` returning at most one objection per message (first match wins), mirroring `extract_property_type`'s "closed-enum, keyword-first" style rather than `extract_timeline_and_must_haves`'s "combined multi-field" style.**

Rationale: unlike financing+decision-mode (US-208, often co-mentioned in one sentence), objection types are typically mutually exclusive complaints in a single message ("está muy caro" is Precio, not also Zona) — modeling as a single best-match closed-enum keeps `ObjectionType` consistent with how `PropertyType` extraction already works, and avoids over-engineering a multi-objection-per-message case with no evidence in the source HU. If a lead raises two distinct objections in one message, they will be captured across two consecutive extractor calls if the Coordinator Agent (future) sends each objection as a separate turn, or missed if genuinely simultaneous — acceptable false-negative per the same "extraction never misclassifies, only occasionally misses" posture as every other extractor in this codebase.

## Risks / Trade-offs

- **[Risk]** The weights/thresholds in Decision 1 are not sourced from a business stakeholder → **Mitigation**: documented explicitly above as an open question; `LeadScoringService` isolates the rule behind one function (`compute_lead_score`) so it's a one-file change to retune later, with no schema migration needed (the formula, not the data, would change).
- **[Risk]** Recomputing `lead_score` locally can conflict with `Lead.mark_synced()` overwriting it from wacrm on the next CDC poll, silently discarding the objection-based penalty → **Mitigation**: documented as a known conflict, not resolved in this change (matches the proposal's BREAKING note). `mark_synced()` is left unchanged; whichever writer runs last wins. A follow-up story should either (a) make wacrm authoritative and stop local writes, or (b) make the local objection penalty an adjustment layered on top of the synced base score instead of a replacement. Flagged for human/product review.
- **[Risk]** Keyword-based objection detection has false negatives for indirect phrasing (e.g. "no sé, tal vez" as a soft price objection) → **Mitigation**: same posture as every other Sprint 2 extractor — a missed extraction just means no signal was captured, never a wrong signal; acceptable for a first cut, revisit with LLM-backed Objection Handler later (source HU's own "Alineación (b)").

## Migration Plan

1. Add `alembic/versions/0007_sprint2_1_lead_objections.py` (chains off `0006_sprint2_1_buyer_profile_dimensions`): create `lead_objections` table, add nullable `lead_classification` column to `leads` (default `'HOT'` at the application layer, nullable at the column level for backward compatibility with existing rows — a backfill statement sets existing rows to `'HOT'` as the neutral safe default since no objection history exists for them yet).
2. Deploy domain/application code together with the migration — additive table + additive column, no maintenance window needed.
3. No further backfill beyond the `'HOT'` default set in the migration.
4. Rollback: `alembic downgrade -1` drops `lead_objections` and the `lead_classification` column; application code must roll back in the same deploy.

## Open Questions

- Should the exact scoring weights (15.0/5.0 penalties, 70/40 thresholds) be product/sales-owned config (`get_settings()`-style) instead of hardcoded constants? Left hardcoded in `LeadScoringService` for this first cut, matching `profile_completeness_threshold`'s pattern of being a `Settings` field — **flagged for human reviewer**: consider promoting to `Settings` once the values are validated with the commercial team.
- Should `mark_synced()` and the local objection-based recompute be reconciled (Risk above)? Left open, flagged for a follow-up story.
