## Context

`Documents/Oficial/AI_Recommendation_Domain_Model.md` §4 already proposes the `conversation_memory` schema (`id, conversation_id, lead_id, memory_type, entity_name, value jsonb, confidence, created_at`) as one of only two genuinely new tables Epic 2/3 needs (the other being `recommendations`, US-310, out of scope here). The source HU (AI-102) explicitly frames this as free-text signal extraction — style adjectives, family context, tone — that is materially different from the closed-enum/range dimensions `BuyerProfileCaptureService` already captures, and states its own scope boundary: "capa agentic Requirement Extraction, cero código hoy" and "bloquea a US-211 (fuera de este scope)". This design covers only the AI-102 slice: the table, the domain shape, and a first deterministic extractor — not US-211's affinity-profile inference.

## Goals / Non-Goals

**Goals:**
- Stand up `conversation_memory` exactly matching the already-documented schema (no schema invention).
- Insert observations from free text without ever touching `BuyerProfile`/`PROFILE_DIMENSIONS` — the two systems run in parallel by design.
- Ship a working first-cut extractor now, using the same deterministic keyword/pattern approach as every other Sprint 2 extractor, even though free-text style/tone signal is, by nature, a stronger long-term candidate for LLM extraction than the closed-enum dimensions US-202-209 capture.

**Non-Goals:**
- No LLM call in this change. The source HU's own alignment section describes the future Requirement Extraction agentic layer as "cero código hoy" — this proposal explicitly keeps it that way for now and ships a deterministic keyword-based first cut instead, matching the codebase-wide Sprint 2 posture (see US-208/US-209 design docs for the same non-goal pattern).
- No affinity-profile inference or consumption of `conversation_memory` (US-211) — this change only writes the table, nothing reads it downstream yet.
- No `tone` extraction in this first cut (see Decision 2) — tone requires sentiment/register inference that a keyword table cannot reliably approximate; shipping a fake "tone" signal from crude keyword matching would be worse than not shipping one, so this dimension is explicitly deferred.

## Decisions

**Decision 1 — New bounded-context module `app/modules/conversation_memory/`, not folded into `lead_qualification`.**

The proposal's own capability classification calls this a **New Capability**, and the source HU's alignment note (a) is explicit that this is "transversal a Discovery, corre en paralelo a PROFILE_DIMENSIONS, no reemplaza BuyerProfileCaptureService" — i.e., a materially different concern (unstructured signal capture) from `lead-qualification`'s structured profiling, even though both currently read the same lead conversational stream. Keeping it a separate module avoids conflating two different completeness/gating semantics: `BuyerProfile.completeness()` gates `Qualified`; `conversation_memory` rows never gate anything in this change.

Alternative considered: add the extractor to `qualification_flow.py` alongside the other extractors, since it's the same lead-conversation entry point. Rejected — `qualification_flow.py`'s docstring and every existing function there is scoped to `ProfilePatch`/`BuyerProfileCaptureService`; forcing a structurally different return shape (an observation list, not a `ProfilePatch`) into that file blurs the module's single responsibility and the proposal's own "New Capability" classification.

**Decision 2 — First-cut `MemoryType` covers `STYLE_PREFERENCE` and `FAMILY_CONTEXT` only; `TONE` is deferred.**

The source scenario only requires "una fila... con memory_type, entity_name, value y confidence" for a style-preference example; the broader HU description also mentions family context and tone as illustrative signal types, but tone is fundamentally a continuous/sentiment signal, not a keyword-matchable discrete one. Shipping `STYLE_PREFERENCE` (interior-style adjectives: minimalista, luminoso, moderno, clásico, acogedor, elegante, rústico, contemporáneo) and `FAMILY_CONTEXT` (family-composition phrases: "tenemos hijos", "vivimos solos", "somos una pareja sin hijos", "tenemos mascota") gives two concrete, testable, keyword-safe categories now; `TONE` is left as a documented `MemoryType` enum placeholder value with no extractor wired to it yet, so adding it later needs no migration — just a new keyword table and a new branch in the extractor.

**Decision 3 — Extractor never overwrites, always appends; multiple observations per message are allowed (unlike US-209's single-best-match objection extractor).**

Unlike `extract_objection` (US-209, closed-enum, at most one type per message), a single free-text message can plausibly carry both a style cue and a family-context cue in the same sentence ("buscamos algo minimalista para nuestra familia con dos niños"). `extract_conversation_memory` therefore returns a list of zero or more `ConversationMemoryObservation` (one row inserted per match), closer in spirit to `extract_timeline_and_must_haves`'s "multiple signals, one message" pattern than to `extract_objection`'s "one winner" pattern — but as independently insertable rows rather than fields merged into one patch, since `conversation_memory` is append-only history, not a single mutable profile.

**Decision 4 — Fixed placeholder `confidence` per match, not a computed score.**

Since detection is exact keyword matching (a keyword is either present or not — no partial-match probability to report), `confidence` is a constant `0.6` for every keyword-matched observation in this first cut, documented explicitly as a placeholder pending the eventual LLM-backed extractor (which would produce a genuine model confidence). `0.6` (moderately-but-not-fully confident) was chosen over `1.0` specifically so that a future consumer (US-211) can distinguish keyword-matched observations from higher-confidence LLM-extracted ones once both coexist, without a migration to add a "source" column later — the confidence value itself already signals "first-cut / deterministic" provenance. **Flagged for human/product review**: this is an implementer default, not a sourced business rule.

**Decision 5 — `conversation_memory.conversation_id` is required (matches the documented schema's `FK`, not nullable), so the extractor's caller must supply it.**

Unlike `qualification_flow.py`'s extractors (which only need `lead_id`), this extractor's signature takes both `conversation_id` and `lead_id` — matching the schema exactly (§4 lists `conversation_id uuid FK` as a top-level field, not optional). The (future) Coordinator Agent already has both by the time it dispatches to any extractor.

## Risks / Trade-offs

- **[Risk]** Keyword-based style/family detection is genuinely weaker than for the other Sprint 2 extractors (style adjectives are far more open-ended than a closed `PropertyType` enum) → **Mitigation**: explicitly scoped as a first cut in this design; false negatives are safe (same posture as every other extractor — a missed style cue is simply not recorded, never misrecorded); the fixed `0.6` confidence signals "treat with more skepticism than a hard-field capture" to any future consumer.
- **[Risk]** No consumer exists yet for `conversation_memory`, so this change ships write-only infrastructure → **Mitigation**: intentional, matches the source HU's own scope boundary (blocks US-211, not delivered here); the table and extractor are independently testable and valuable groundwork.
- **[Risk]** A new bounded-context module adds structural surface (new package, new migration, new `app/main.py` import) for a currently-small feature → **Mitigation**: judged worth it given the proposal's own "New Capability" framing and the HU's explicit statement that this is materially distinct from `lead-qualification`; keeps `qualification_flow.py` from accumulating unrelated concerns.

## Migration Plan

1. Add `alembic/versions/0008_sprint2_1_conversation_memory.py` (down_revision `0007`): `create_table("conversation_memory", ...)` with `conversation_id`/`lead_id` FKs, `value` as JSON (JSONB semantics via SQLAlchemy's portable `JSON` type, matching how `buyer_profiles.locations`/`must_haves` already use `JSON` rather than a Postgres-specific `JSONB` import, for the same SQLite-test-portability reason documented in `db_models.py`'s module docstring), `confidence` as `Float`.
2. Deploy the migration together with the new module's code — purely additive, no existing table touched, no maintenance window.
3. No backfill (new table, no historical `conversation_memory` data exists anywhere to backfill from).
4. Rollback: `alembic downgrade -1` drops `conversation_memory`; application code (the new module) must roll back in the same deploy since nothing else depends on it yet, so there's no cross-module breakage risk either direction.

## Open Questions

- Should `confidence=0.6` be a named `Settings` constant instead of a hardcoded literal, so it's tunable without a code change once real usage data exists? Left as a module-level constant for this first cut; flagged for follow-up alongside US-209's similar open question about promoting its scoring weights to `Settings`.
- Should `TONE` be added as a real extractor in a near-term follow-up, or wait for the LLM-backed Requirement Extraction layer entirely? Left open — the enum placeholder exists either way, so this is a scheduling decision, not a technical blocker.
