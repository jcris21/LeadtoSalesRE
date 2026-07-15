## Context

`BuyerProfile` (`app/modules/lead_qualification/domain/models.py`) is the structured output of progressive conversational qualification. `PROFILE_DIMENSIONS` (currently 5 elements) drives `completeness()`, which gates the QA-14 `ProfileCompleted` event and the CRM `Qualified` stage transition. Extraction is deterministic keyword/regex matching in `qualification_flow.py`, no LLM. US-208 adds two new dimensions the Customer Journey requires (`financing_type`, `decision_maker_mode`) but doesn't specify whether they should count toward the completeness gate.

## Goals / Non-Goals

**Goals:**
- Capture `financing_type` and `decision_maker_mode` on `BuyerProfile` via the same progressive-profiling mechanism as the existing 5 dimensions.
- Keep the extraction deterministic (keyword-based), consistent with existing extractors.
- Preserve backward compatibility for existing `buyer_profiles` rows (new columns nullable).

**Non-Goals:**
- No LLM-backed extraction (out of scope; AI-102 handles free-text signal extraction separately into `conversation_memory`, a different table/concern).
- No change to the wacrm sync contract — these fields are local-only qualification signal, not pushed to CRM in this change.
- No UI/API surface changes beyond optionally exposing the fields on read schemas.

## Decisions

**Decision 1 — Count both new fields toward `PROFILE_DIMENSIONS` (5 → 7), do not create a separate "optional metadata" bucket.**
Rationale: the Customer Journey document treats financing and decision-maker mode as equally material to qualification as budget/location; US-209 (Hot/Warm/Cold) is expected to consume both signals for scoring. Splitting them into a non-gating bucket would need a second completeness concept, adding complexity without a stated requirement for it.
Alternative considered: keep `PROFILE_DIMENSIONS` at 5 and add the two fields as non-gating metadata. Rejected — no evidence in the source HU or Backlog.md that they should be excluded from the gate, and doing so would silently diverge from the documented Customer Journey.

**Decision 2 — Do not adjust `profile_completeness_threshold` as part of this change.**
Rationale: the threshold is a percentage (`get_settings().profile_completeness_threshold`), and extending the denominator from 5 to 7 already produces a proportionally stricter gate automatically — a lead now needs to answer 2 more questions to reach the same percentage. This is the intended tightening (more signal required before declaring `Qualified`), not a bug to compensate for. If product later decides the two new dimensions are lower-priority, that's a follow-up threshold/config change, not part of this proposal.

**Decision 3 — Single combined extractor `extract_financing_and_decision_mode`, mirroring `extract_timeline_and_must_haves`.**
Rationale: financing and decision-maker signals often appear together in a single lead message (e.g. "vamos a comprar en pareja, con crédito hipotecario"); a combined extractor returning one `ProfilePatch` for both avoids two round trips through `BuyerProfileCaptureService.update_profile` for a single message, consistent with the existing `extract_timeline_and_must_haves` pattern.

**Decision 4 — New enums are additive, no changes to existing enums (`Timeline`, `PropertyType`).**

## Risks / Trade-offs

- **[Risk]** Lowering the relative completeness of in-flight profiles could delay some leads from crossing the QA-14 threshold who were previously close to complete → **Mitigation**: this is the intended behavior change (documented in proposal.md as a behavioral BREAKING note); no code mitigation needed, but flag to product/business owner before merge since it changes when `Qualified` fires for profiles already in progress at deploy time.
- **[Risk]** Migration adds two nullable columns — low risk, backward compatible, no backfill needed since `None` is a valid "not yet captured" state identical to the existing 5 dimensions before completion.
- **[Risk]** Keyword extraction for financing type in Spanish has ambiguity (e.g. "estoy evaluando" could mean "evaluating financing" or "evaluating properties in general") → **Mitigation**: require financing keywords to appear near payment-related context words, consistent with how `_MUST_HAVE_MARKERS` scopes its match; false negatives (no extraction) are safe — the lead is simply re-asked later, never silently misclassified.

## Migration Plan

1. Add `alembic/versions/0006_sprint2_1_buyer_profile_dimensions.py` — `op.add_column` for `financing_type` and `decision_maker_mode` (both nullable `VARCHAR`), reversible via `op.drop_column` in `downgrade()`.
2. Deploy domain/application code changes together with the migration (single change, no phased rollout needed — additive nullable columns are safe to deploy without a maintenance window).
3. No backfill required.
4. Rollback: `alembic downgrade -1` drops the two columns; application code must be rolled back in the same deploy since `BuyerProfileRepository` would otherwise reference missing columns.

## Open Questions

- Should `financing_type`/`decision_maker_mode` be surfaced to wacrm via the Lead Sync Adapter in a future change? Out of scope here; flagged for a follow-up story if commercial team wants it CRM-visible.
