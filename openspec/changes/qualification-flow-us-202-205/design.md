## Context

`qualification_flow.py` and `qualification_turn.py` already implement and wire the four
progressive-profiling dimensions in scope (US-202–US-205) into the real conversational turn via
`CoordinatorAgent`. This is a closeout change, not a greenfield build: the design decisions below are
about the small remaining gaps, not the overall architecture (which is unchanged Prompt Chaining per
`Agentic_System.md` pattern #1).

## Goals / Non-Goals

**Goals:**
- Deduplicate `must_haves` extracted from a single message.
- Prove (via tests, not new code) that budget extraction tolerates currency words/symbols next to
  the amount.
- Prove that `timeline` and `must_haves` survive independently across separate turns.
- Bring `Documents/Oficial/HU_Calificacion_Recomendacion.md` in line with the actual, already-shipped
  conversational entry point.

**Non-Goals:**
- Adding a `currency` field to `MoneyRange`/`buyer_profiles` — the domain model deliberately stores
  amounts "as given by the conversation" (see `models.py` docstring); introducing multi-currency
  support is a separate, larger change with schema impact, out of scope here.
- Semantic (synonym-based) must_haves deduplication ("cochera" vs. "estacionamiento") — only textual
  (case/whitespace-insensitive) dedup within one message is in scope; semantic merging would require
  an LLM call this dimension doesn't otherwise need.
- Any change to `qualification_turn.py`'s routing logic, `CoordinatorAgent`, or the REST support
  endpoints — all already correct and tested.
- Touching `app/modules/recommendation/**`, `intent_router.py`, `link_guard.py`,
  `neighborhood_enrichment.py`, or anything US-307/AI-104/scheduling-related.

## Decisions

- **Dedup scope = single message, textual only.** `_extract_must_haves` already splits one message's
  free text into a tuple of items; adding `dict.fromkeys(normalized_item -> original_item)`-style
  dedup at that point is a two-line change with no new dependency and no behavior change for the
  (already-tested) non-duplicate case. Cross-turn accumulation of `must_haves` is unaffected: each
  turn's `ProfilePatch.must_haves`, when present, still fully replaces the field on
  `BuyerProfile.apply` (existing, tested behavior — a `ProfilePatch` is a snapshot of what the lead
  said *this turn*, not an incremental delta to merge with prior state). This scoping keeps the
  change minimal and avoids opening the larger "should must_haves accumulate across turns"
  discussion, which the enrichment doc explicitly left as an open decision for a future sprint.
- **Currency robustness: mostly already there, one real gap found and fixed.** A single amount with a
  trailing currency word ("150000 dólares") already matched, since the currency word is simply outside
  the digit-matching group. A *range* with a currency symbol immediately before the *second* number
  ("$100,000 y $150,000") did not match `_RANGE_RE`, because the pattern required a digit right after
  the separator with no room for a currency prefix — the "y $150,000" segment failed to match and the
  whole range fell back to matching only the first amount as a single value. Fixed with a small,
  optional `_CURRENCY_PREFIX` (`$`, `S/`, `USD`, `US$`) matched-but-not-captured before each amount
  group in both `_RANGE_RE` and `_SINGLE_RE`. This was discovered while writing the currency test
  cases this change adds (task 3.1), not assumed up front.
- **HU doc update is part of this change, not a follow-up.** Per the enrichment doc's own instruction
  ("actualizar... solo cuando el flujo conversacional real exista"), and since
  `test_e2e_script_fills_profile_and_fires_profile_completed` already proves that flow exists end to
  end, flipping the four HU rows to "Implementado" is in scope now rather than deferred again.

## Risks / Trade-offs

- [Risk] Dedup could hide a legitimate repeated requirement phrased identically on purpose (rare in
  practice for a single message) → Mitigation: dedup is scoped to one message/one `ProfilePatch`,
  order-preserving, case/whitespace-insensitive only — never touches items already persisted from a
  prior turn.
- [Risk] The HU doc status flip could look like new functionality shipped, when it is documentation
  catching up to code that shipped weeks ago → Mitigation: proposal.md and this design.md make the
  timeline explicit; the Alineación (b) column is updated to name the real entry point.

## Migration Plan

No data migration. Code change is additive/corrective only (dedup); doc change is a status/text
update. Rollback is a plain revert of the two touched files plus the HU doc edit.

## Open Questions

- Should `must_haves` (and `locations`) accumulate across turns instead of being replaced per-patch?
  Left open per the enrichment doc's own note — out of scope for this change.
