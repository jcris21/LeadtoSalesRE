## Context

`app/modules/lead_qualification/domain/models.py` and
`app/modules/lead_qualification/application/profile_capture.py` already implement the deterministic
half of progressive profiling: `BuyerProfile.apply(patch)`, `ProfilePatch` validation
(`ProfileValidationError`), and `BuyerProfileCaptureService.update_profile` (persists to
`buyer_profiles`, emits `ProfileCompleted` when completeness crosses the org threshold). There is no
module under `app/modules/lead_qualification/api/`, and no LLM extraction layer — nothing today turns
a lead's WhatsApp message into a `ProfilePatch`. `Documents/Oficial/Agentic_System.md` already
documents the target shape (Qualification Flow = Prompt Chaining, pattern #1) but it was never built.
Four HUs (US-202 budget, US-203 locations, US-204 property_type, US-205 timeline/must_haves) all block
on this one missing piece, so this design covers all four together instead of separately.

## Goals / Non-Goals

**Goals:**
- One `qualification_flow.py` module with one sub-prompt (or lightweight extractor) per dimension,
  each producing a `ProfilePatch` and delegating persistence to the existing
  `BuyerProfileCaptureService.update_profile` — no new persistence logic.
- Support/QA REST endpoints per dimension so the capture can be exercised and tested without wiring
  a live LLM conversation first.
- Tenant isolation: every write path validates the lead's `organization_id` before calling
  `update_profile`.
- `ProfileValidationError` never reaches the caller as a raw 500 — translated to a re-prompt
  (conversational) or 422 (REST).

**Non-Goals:**
- Building the full Coordinator Agent / Intent Router (AI-104, separate gap, out of scope here).
- Wiring the Qualification Flow into the live Chatwoot webhook / conversation turn loop — that
  requires the Coordinator Agent to route into it, which does not exist yet. This change makes the
  Qualification Flow callable and testable in isolation (via the sub-prompt functions and the support
  endpoints); full conversational wiring is a follow-up once AI-104 lands.
- Changing `PROFILE_DIMENSIONS`, `BuyerProfile`, `ProfilePatch`, or any ORM/table schema.
- Zone catalog normalization for `locations` (US-203) — no such catalog exists yet; documented as an
  open question below, not built in this change.

## Decisions

- **One module, four sub-prompts, not four modules.** `qualification_flow.py` houses
  `extract_budget`, `extract_locations`, `extract_property_type`, `extract_timeline_and_must_haves` —
  keeps `ProfileValidationError` handling, the `update_profile` call, and the tenant check in one
  place instead of duplicated four times. Considered: one file per dimension — rejected, it would
  duplicate the wiring boilerplate for no isolation benefit (all four write the same aggregate).
- **`property_type` uses keyword matching first, LLM fallback only for `other`/ambiguous.** It is a
  5-value closed enum; a full LLM call per message is unnecessary cost/latency. `budget`, `locations`,
  and `timeline`/`must_haves` need LLM extraction (free-form amounts, free-form zones/requirements).
  Considered: LLM for all four uniformly — rejected on cost grounds for the one dimension that doesn't
  need it.
- **Support endpoints are REST, one per dimension, mirroring the domain's patch shape 1:1.** Considered
  a single combined `PATCH /profile` endpoint — deferred: US-205 already needs to test `timeline` and
  `must_haves` both together and separately, so a combined endpoint doesn't remove test surface, it
  only adds one more shape to validate. Per-dimension endpoints keep each test scenario simple; a
  combined endpoint can be added later without touching this design if the LLM flow ends up needing it.
- **Qualification Flow functions are called directly, not exposed as a public HTTP surface.** The LLM
  extraction is invoked from wherever the (future) Coordinator Agent or conversation turn handler
  lives — this change only makes those functions exist and be independently testable. The REST
  endpoints are separate, support-only, and do not call through the LLM sub-prompts.

## Risks / Trade-offs

- [No live conversational entry point yet] → Mitigation: this change is explicitly scoped to make the
  extraction + persistence path exist and be testable; the HU rows in
  `HU_Calificacion_Recomendacion.md` stay "Parcial" until AI-104 (Coordinator Agent) routes real
  conversation turns into `qualification_flow.py`. Documented, not silently implied as "done".
- [LLM extraction for `budget`/`locations`/`timeline`/`must_haves` can misparse free text] →
  Mitigation: `ProfilePatch`/`MoneyRange` already validate ranges and non-empty tuples; the sub-prompt
  must not call `update_profile` when it cannot confidently extract a value — re-prompt instead of
  guessing.
- [Support endpoints could accidentally become the "real" integration surface if the LLM flow slips] →
  Mitigation: name them explicitly as support/QA in code comments and this doc; do not link them from
  any customer-facing route.
- [Cross-tenant write if `lead_id` isn't checked against caller's `organization_id`] → Mitigation:
  every endpoint and every sub-prompt call path fetches the lead via `LeadRepository` (already scoped)
  and rejects if `lead.organization_id` doesn't match the request/session context — same pattern
  `update_profile` already uses internally via `LeadNotFoundError`.

## Migration Plan

No data migration — no schema changes. Deploy as a normal code change:
1. Add `qualification_flow.py` and `api/router.py`, register router in `app/main.py`.
2. Ship behind existing auth/tenant middleware (no new deployment flags needed).
3. Rollback = revert the two new files and the one-line router registration in `app/main.py`; no data
   to unwind since `update_profile` was already the sole write path before and after this change.

## Open Questions

- Should `locations` normalize against an org-level zone catalog? No such catalog exists today
  (confirmed: no reference table in `lead_qualification/infrastructure`). Deferred — out of scope,
  flagged in the enrichment doc (`openspec/specs/lead-qualification/us-202-205-enrichment.md`).
- Should `must_haves` deduplicate semantically-equivalent free text (e.g. "cochera" vs
  "estacionamiento")? Deferred to the sub-prompt's discretion in this change; not a hard requirement.
