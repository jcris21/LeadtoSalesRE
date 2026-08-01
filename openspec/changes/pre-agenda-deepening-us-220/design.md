## Context

`CoordinatorAgent._conversational_turn` already runs two additive, deterministic orchestration steps
gated on `ConversationState.RECOMMENDATION` before the `ResponderPort` call: `_build_grounding_note`
(QUALIFICATION-gated, unrelated) and `_scheduling_turn` (US-212). Both follow the same shape: check a
state gate, do deterministic (non-LLM) work, and either fall through unchanged or short-circuit the
reply with a canned message. The new deepening turn follows the identical shape, inserted immediately
before `_scheduling_turn` in the call order, since its whole purpose is to make sure
`_scheduling_turn`'s property resolution (`_latest_top_pick`) has a trustworthy answer by the time a
slot is confirmed.

`RecommendationORM` (`app/modules/recommendation/infrastructure/db_models.py`) already has a
`feedback: Mapped[dict | None]` column with the docstring "Reserved for future feedback events
(learning loop) — no writer yet." This is exactly the persistence seam US-220 needs and the doc's own
alignment note (c) requires ("Ninguna tabla nueva") — no migration, no new column.

## Goals / Non-Goals

**Goals:**
- Ask the lead which Top-3 option interested them, once, only when there's real ambiguity to resolve
  (2+ recommended properties) and only until a selection is recorded.
- Make the lead's selection the source of truth for which property `run_scheduling_turn` books,
  overriding the pipeline's original rank-1 default.
- Stay purely additive: a single-property recommendation, a `QUALIFICATION`-state message, or an
  unlinked lead must behave exactly as before this change (zero risk to `test_coordinator_qualification_turn.py`,
  `test_coordinator_grounding_note.py`, and the existing single-item
  `test_coordinator_scheduling_turn.py` fixtures).
- Never guess: option recognition is deterministic (regex/keyword), same "no match -> None" contract
  as `extract_confirmed_slot`/`extract_identity`/the qualification extractors.

**Non-Goals:**
- The natural-language scheduling *invitation* itself ("la opción 2 se ajusta a lo que buscas, ¿coordinamos
  una visita?") — that is US-221, explicitly out of scope here and left to the existing LLM
  responder/system prompt.
- Re-ranking or persisting a "why the lead chose this" explanation — `feedback` stores only a boolean
  marker (`{"selected_by_lead": True}`), not a learning-loop payload; that remains a future use of the
  same column.
- Recognizing option references by natural property description ("la de Miraflores", "la más barata")
  — scoped to ordinal/numeric references only (Non-Goal, same spirit as US-212's slot-recognition
  scope limit); a lead phrasing it that way simply gets asked again next turn (safe degradation, not a
  regression, since nothing was previously implemented here at all).

## Decisions

**Decision 1: Gate on batch size ≥ 2, not on "first reply since narration".**
The Gherkin's "el siguiente turno...pregunta cuál opción" reads as a single deepening exchange right
after narration, but tracking "has this batch already had its one deepening turn" without a new
column requires *some* persisted signal — and `feedback` already serves that purpose once a selection
is made. Gating on "2+ properties AND no selection recorded yet" achieves the same practical outcome
(ask until resolved, then stop) without inventing a second, redundant "already asked" flag, and — load-bearing
for this change — a batch of exactly one recommended property has no real "which one" question to ask
in the first place, so it is `not_applicable` by construction. This is also the reason the existing
`test_coordinator_message_without_slot_falls_through_to_responder` fixture (single-item batch) needs
zero modification: the new turn never engages for it.

**Decision 2: Selection persistence reuses `RecommendationORM.feedback`, not a new table/column.**
Per the HU doc's own alignment note (c) and the general no-new-table constraint: `feedback` is
JSON-typed, nullable, and explicitly reserved for exactly this kind of event. `mark_selected` writes
`{"selected_by_lead": True}` on the chosen row within the latest batch. No other row is touched,
so a stale marker from an older, already-superseded batch is naturally impossible (the deepening turn
and `_latest_top_pick` both scope to `max(generated_at)` first).

**Decision 3: `_latest_top_pick` prefers a lead-selected row before falling back to rank.**
This is the one change to `scheduling_turn.py`, and it is deliberately narrow: a new
`is_lead_selected(row) -> bool` helper and one `next(...)`-before-`min(...)` line. Every existing
scheduling_turn test seeds a single-row batch, so `is_lead_selected` never finds a match there and the
existing rank-1 behavior is preserved byte-for-byte for those fixtures.

**Decision 4: A message carrying an explicit slot bypasses the deepening question outright.**
If the lead already jumped straight to "el sábado a las 3pm" without confirming an option, blocking
that message with "¿cuál opción te interesó?" would be a worse conversational experience than letting
`_scheduling_turn` proceed with its existing rank-1 fallback (the same behavior as before this change
existed). Gate order in `run_deepening_turn`: batch-size/already-selected checks first, then
`extract_confirmed_slot(text) is not None` short-circuits to `not_applicable` before rank-recognition
is even attempted.

**Decision 5: Deepening turn runs before `_scheduling_turn`, never after.**
`_scheduling_turn`'s own contract only fires on a message carrying a slot; ordering it after the
deepening turn means a message that answers "opción 2" (no slot) is fully handled by deepening alone
(outcome `"selected"`, falls through to the normal responder afterward, mirroring the DNI-nudge
additive posture), while a message carrying both an answer and a slot in the same turn is not
supported (Non-Goal) — the lead is expected to answer the deepening question in its own turn, matching
the Gherkin's own two-turn structure ("el lead responde... el siguiente turno...").

## Risks / Trade-offs

- [Risk] A lead who mentions a bare digit unrelated to option selection (e.g. "tengo 2 hijos") inside
  a multi-item RECOMMENDATION-state message before any slot is stated could be misread as selecting
  rank 2 → Mitigation: scoped, documented limitation, same class of risk `extract_confirmed_slot`
  already accepts for date-like text; a misfire only changes which property later gets booked, it
  never crashes the turn, and a lead can still say "no, la opción 1" to correct it since re-selection
  simply overwrites `feedback` on the newly matched row (the old marker is cleared as part of the same
  `mark_selected` call, one property flagged per batch at a time).
- [Trade-off] Not gating on "first reply only" means the deepening question can repeat across multiple
  turns if the lead keeps giving unrelated answers → accepted: this is strictly better than silently
  proceeding to scheduling against the wrong (rank-1) property, and mirrors the DNI nudge's own
  "keep nudging until resolved" posture.
- [Risk] Reusing `feedback` for this narrow purpose could collide with a later, broader "feedback
  events" writer → Mitigation: the key `selected_by_lead` is a scoped, namespaced boolean; a future
  richer feedback payload can add sibling keys without conflict, and this is called out explicitly so
  future changes touching `feedback` are aware of the existing writer.
