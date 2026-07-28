## Why

Every new lead is currently asked for their full name on the very first turn,
before the AI has shown any value (no recommendation, no answered question).
US-218 (`Documents/Oficial/HU_Calificacion_Recomendacion.md`) asks to move
identity capture — specifically DNI — past a value moment, to reduce early
abandonment. The doc's own alignment note flags a caveat: wacrm (the CRM,
System of Record for leads) "probablemente exige algún identificador" and
that must be validated before assuming the gate can simply be deferred.

## What Changes

- Investigated wacrm's real contract (`WacrmClient.create_lead` /
  `LeadSyncAdapter.create_lead`, `app/modules/lead_qualification/infrastructure/wacrm_client.py`
  and `Documents/Oficial/WACRM_API_Adaptation_Plan.md`): `POST /deals` requires
  `contact_phone` (already known from the channel before any reply) and
  `contact_name` (`str`, non-optional parameter — no default). `contact_dni`
  is already optional (only sent if not `None`). The adaptation plan documents
  `GET`/`PATCH /deals` but not a way to attach a DNI after creation.
  **Conclusion**: name stays the minimal identifier wacrm truly needs upfront
  alongside the phone; DNI is the field that can genuinely be deferred.
- `REPROMPT_IDENTITY` (turn-1 ask, no Lead linked yet) no longer mentions DNI
  — only asks for the full name.
- New `REPROMPT_DNI`, shown only once `conversation.state` reaches
  `RECOMMENDATION` (a Top-3/value moment has already been delivered per
  `recommendation.wiring.handle_profile_completed`) and the lead hasn't
  volunteered a DNI yet. Additive — appended to whatever reply the turn
  already produced, never overriding qualification, scheduling, or knowledge
  answers (unlike the name gate, which legitimately blocks until a Lead
  exists to attach a reply to).
- DNI can still be volunteered opportunistically at turn 1 alongside the name
  (unchanged, already supported) or later, in reply to `REPROMPT_DNI`
  (`extract_dni`) — either way it is excluded from qualification extraction
  the same turn it's consumed (same convention as the existing
  `identity_consumed` flag).

### New Capabilities
(none — this refines existing Identity Gate behavior in `conversation-ownership`/`lead-qualification`)

### Modified Capabilities
- `lead-qualification`: identity capture ordering — DNI request deferred from
  turn 1 to the `RECOMMENDATION` state; additive rather than blocking.

## Impact

- `app/modules/lead_qualification/application/identity_extraction.py` —
  `REPROMPT_IDENTITY` text, new `REPROMPT_DNI`, new `extract_dni`.
- `app/modules/conversation_ownership/application/coordinator.py` — new
  `_dni_gate`, wired into `handle_message`/`_conversational_turn`. No changes
  to `_identity_gate`'s creation logic itself (dni already optional there).
- No `leads` table schema change (existing `ConversationState.RECOMMENDATION`
  bounds the ask window without a new persisted flag).
- No `WacrmClient`/`LeadSyncAdapter` contract change.
- Tests: `tests/test_coordinator_identity_gate.py` and/or a new
  `tests/test_coordinator_dni_gate.py`.
