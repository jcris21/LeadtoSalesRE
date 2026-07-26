## Why

`Documents/Oficial/HU_Calificacion_Recomendacion.md` still lists US-202 (budget), US-203
(locations), US-204 (property_type), and US-205 (timeline/must_haves) as "Parcial", on the premise
(carried over from `openspec/specs/lead-qualification/us-202-205-enrichment.md`, the `/enrich-us`
output for these four stories) that no conversational entry point invokes
`BuyerProfileCaptureService.update_profile` from a real chat turn.

That premise is now stale. `app/modules/lead_qualification/application/qualification_flow.py`
(Prompt Chaining, `Agentic_System.md` pattern #1) and its orchestrator
`app/modules/lead_qualification/application/qualification_turn.py` already extract all four
dimensions from a lead's message and persist them via `update_profile`; `CoordinatorAgent.handle_message`
already calls `run_qualification_turn` on every real turn once a `Lead` is linked
(`app/modules/conversation_ownership/application/coordinator.py`). This is a real conversational
entry point, proven end-to-end by `tests/test_coordinator_qualification_turn.py`'s
`test_e2e_script_fills_profile_and_fires_profile_completed`. The original OpenSpec change for this
work (`openspec/changes/archive/2026-07-15-qualification-dimensions-us-202-205`) explicitly deferred
the Coordinator wiring and kept the HU rows at "Parcial" for that reason; the wiring landed in a
later commit (`69a27fe`) without a follow-up change or HU update, leaving the documentation out of
sync with the code and leaving a few small edge cases the original enrichment DoD called out
(must_haves deduplication, budget/currency robustness, cross-turn independence for timeline vs.
must_haves) unverified by tests.

## What Changes

- Deduplicate `must_haves` items extracted from a single message in
  `extract_timeline_and_must_haves` (case/whitespace-insensitive, order-preserving) so a message
  like "cochera, cochera" never persists the same requirement twice.
- Add test coverage for budget messages that mix currency words/symbols with the amount (e.g.
  "$150,000", "150,000 dólares", "S/ 200,000 soles"), and for a single amount vs. an explicit range.
  Writing these tests surfaced one real gap: a range with a currency symbol before the *second*
  number (e.g. "$100,000 y $150,000") failed to match `_RANGE_RE`; fixed with a small optional
  currency-prefix group in the regex (see design.md).
- Add a test proving `timeline` and `must_haves` can each be captured in separate turns without one
  turn's patch erasing the other's already-captured dimension (only cross-field non-erasure across
  unrelated dimensions is tested today).
- Add a test for the property_type ambiguous/ two-mentions case documenting the "captures first
  match" rule already implemented.
- Update `Documents/Oficial/HU_Calificacion_Recomendacion.md` rows for US-202, US-203, US-204,
  US-205 from "Parcial" to "Implementado", with each row's Alineación (b) column pointing at the
  real conversational entry point (`qualification_flow.py` + `qualification_turn.py` wired into
  `CoordinatorAgent`) instead of "extractor + endpoint, sin enrutamiento conversacional".

## Capabilities

### New Capabilities
(none — no new capability; this change closes out requirements already declared for the existing
`lead-qualification` capability)

### Modified Capabilities
- `lead-qualification`: adds explicit requirements for must_haves deduplication within a message and
  for the budget/locations/property_type/timeline extractors being reachable from the real
  conversational turn (not only from the support endpoints), reflecting behavior that already exists
  in code but was never captured as a spec requirement.

## Impact

- **Code**: small edit to `app/modules/lead_qualification/application/qualification_flow.py`
  (`_extract_must_haves` dedup only); no changes to `qualification_turn.py`,
  `profile_capture.py`, `coordinator.py`, or any domain model/schema.
- **No schema changes.**
- **Docs**: `Documents/Oficial/HU_Calificacion_Recomendacion.md` rows for US-202–US-205 move to
  "Implementado".
- **Tests**: new/extended cases in `tests/test_qualification_flow.py` and
  `tests/test_coordinator_qualification_turn.py`.
- **Out of scope**: `app/modules/recommendation/**`, `intent_router.py`, `link_guard.py`,
  `neighborhood_enrichment.py`, and anything related to US-307/AI-104/scheduling — those are being
  worked in parallel on other branches.
