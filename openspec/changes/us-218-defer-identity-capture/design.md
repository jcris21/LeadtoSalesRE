## Context

`CoordinatorAgent._identity_gate` (`app/modules/conversation_ownership/application/coordinator.py`)
runs before qualification on every turn while `conversation.lead_id is None`.
It blocks the reply with `REPROMPT_IDENTITY` — which currently asks for both
full name *and* (optionally) DNI — until the contact sends a message
`extract_identity` recognizes as a name. Only then is
`LeadSyncAdapter.create_lead` called, which creates the deal in wacrm (SoR)
and links the conversation.

US-218 asks to move DNI/full-name capture past a value moment (a
recommendation or equivalent). Before assuming this is safe, the wacrm
contract needed validating.

**wacrm contract findings** (`wacrm_client.py` + `WACRM_API_Adaptation_Plan.md`):
- `WacrmClient.create_lead(*, contact_reference, contact_name, dni=None)` —
  `contact_phone` and `contact_name` are always sent; `contact_dni` is sent
  only if not `None`. `contact_name` has no default — it is a required
  parameter in this codebase's client today.
- `contact_reference` (the WhatsApp phone) is already known from the channel
  before the contact sends anything — it never needs to be asked.
- `WACRM_API_Adaptation_Plan.md` documents `GET /deals`, `GET /deals/{id}`,
  `PATCH /deals/{id}` (stage + assigned broker only). It does not document a
  way to attach/patch `contact_dni` after the deal already exists, and does
  not relax `contact_name` to optional for `POST /deals`.
- The local `Lead` aggregate mirrors only `crm_lead_id`, `pipeline_stage`,
  `lead_score`, `assigned_broker_id`, `contact_reference` — no `contact_name`
  or `dni` field, and none is being added (per US-218's own alignment note:
  "sin cambio de esquema").

**Conclusion**: full name remains the minimal identifier this codebase can
verify wacrm needs upfront (alongside the already-known phone). DNI is the
field genuinely safe to defer — it was already optional in `create_lead`,
just not in the *conversational ask*, which is what actually drives
abandonment.

## Goals / Non-Goals

**Goals:**
- Turn 1 never asks for DNI, only for the name needed to create the wacrm
  deal.
- DNI is asked once, after a recommendation/value moment
  (`conversation.state == RECOMMENDATION`), without blocking qualification,
  scheduling, or the conversational reply if the contact ignores it.
- No `leads` schema change, no `WacrmClient`/`LeadSyncAdapter` contract
  change.
- Diff confined to `coordinator.py` (identity-gate ordering section) and
  `identity_extraction.py`, to keep the later reconciliation merge against
  US-216/US-217 low-risk.

**Non-Goals:**
- Persisting a durable "DNI already requested/captured" flag (would require
  a `leads` migration — explicitly out of scope per the HU alignment note).
- Adding a wacrm endpoint/contract to patch `contact_dni` post-creation —
  not verified against the real API, so not invented here.
- Changing the RECOMMENDATION FSM transition itself, or `recommendation/wiring.py`.

## Decisions

1. **Keep name mandatory on turn 1, only strip DNI from the ask.**
   Alternative considered: create the lead with a placeholder name (e.g.
   derived from the phone) so *nothing* is asked turn 1. Rejected — this
   would silently corrupt `contact_name` in wacrm (the CRM's own SoR value)
   with no verified way to correct it later, and the doc explicitly allows
   name to stay a turn-1 minimum ("solo nombre/canal mínimos").

2. **Defer the DNI ask, gated on `conversation.state == RECOMMENDATION`,
   not on a persisted flag.**
   Alternative considered: add a `leads.dni_requested_at` (or similar)
   column to ask exactly once and never repeat. Rejected for this change —
   explicitly out of scope (no schema change), and `RECOMMENDATION` is
   itself a bounded window in the FSM (it only precedes `APPOINTMENT`), so
   the nudge naturally stops appearing once the lead moves past it. Trade-off
   accepted and documented below.

3. **DNI ask is additive, never overriding.**
   `ask_identity` (name gate) legitimately *replaces* the turn's reply
   because there is no Lead yet to have a real conversation about. The DNI
   gate has a linked Lead already — overriding qualification/scheduling
   replies to nag for a DNI would reintroduce the same abandonment risk
   US-218 is trying to remove. It is appended as a second line instead.

4. **New `_dni_gate` method, separate from `_identity_gate`.**
   Alternative considered: extending `_identity_gate` itself to also handle
   the deferred case. Rejected — the two have different preconditions
   (`lead_id is None` vs. `lead_id is not None`), different consequences
   (blocking vs. additive), and mixing them would make the "merge-conflict
   zone" `_identity_gate` block noisier for US-216/US-217 reconciliation.

## Risks / Trade-offs

- **[Risk] Without a persisted flag, the DNI nudge can repeat on every turn
  while `state == RECOMMENDATION` and no DNI has been given yet →
  [Mitigation] Bounded by the FSM itself: `RECOMMENDATION` is a narrow window
  before `APPOINTMENT`/scheduling; once past it, the nudge stops. Flagged in
  `proposal.md`/here as a known trade-off, not silently glossed over —
  revisit if telemetry shows it's repeated enough to annoy contacts (would
  then justify a schema change out of this US's scope).
- **[Risk] wacrm's real `POST /deals` contract for `contact_name` isn't
  independently confirmed beyond this codebase's existing client (only
  `GET`/`PATCH` are documented in the adaptation plan) → [Mitigation] No
  behavior change is made to `contact_name`'s requiredness — it stays exactly
  as strict as today. Only the conversational *ask* for DNI moves, which the
  client already treats as optional.
- **[Risk] A message during `RECOMMENDATION` that is purely a DNI answer
  (e.g. "12345678") gets excluded from qualification extraction that turn
  (mirrors the existing `identity_consumed` behavior for the name gate) →
  [Mitigation] Same accepted trade-off as the existing name gate; documented
  in code comments.

## Migration Plan

No data migration. Deploy is a plain code change: update
`identity_extraction.py` (prompt text + new constant/function) and
`coordinator.py` (`_dni_gate` + wiring). Rollback is reverting the commit —
no persisted state to unwind.

## Open Questions

- Should the DNI nudge eventually persist a "captured" flag once schema
  changes are back in scope, to stop repeating past the first
  `RECOMMENDATION` turn? Deferred to a future US per this change's Non-Goals.
