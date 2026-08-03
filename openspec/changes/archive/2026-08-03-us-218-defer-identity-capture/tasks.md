## 1. Identity extraction module

- [x] 1.1 Update `REPROMPT_IDENTITY` (`identity_extraction.py`) to drop the DNI mention — name only.
- [x] 1.2 Add `REPROMPT_DNI` constant for the deferred ask.
- [x] 1.3 Add `extract_dni(text)` helper (DNI-only recognition, no name required alongside it).

## 2. Coordinator identity-gate ordering

- [x] 2.1 Add `_DNI_ELIGIBLE_STATES` (RECOMMENDATION only) near the existing `_KNOWLEDGE_INTENT_CATEGORIES` constant.
- [x] 2.2 Add `CoordinatorAgent._dni_gate` returning `(nudge, dni_consumed)`.
- [x] 2.3 Wire `_dni_gate` into `handle_message`: compute alongside `_identity_gate`, fold `dni_consumed` into the qualification skip condition.
- [x] 2.4 Thread `dni_nudge` into `_conversational_turn` and append it (additive, not overriding) right before `guard_reply`.

## 3. Tests

- [x] 3.1 Turn 1 without a name still asks only for the name (no DNI mention) — reuse/verify existing `test_message_without_name_asks_for_identity_and_creates_nothing`.
- [x] 3.2 Turn 1 with name+DNI still creates the lead with both fields (existing `test_name_message_creates_lead_mirrors_locally_and_links` continues to pass unchanged).
- [x] 3.3 New test: lead created on turn 1 with name only (no DNI) — confirms leads CAN be created/advanced without DNI.
- [x] 3.4 New test: conversation in `QUALIFICATION` state never shows the DNI nudge.
- [x] 3.5 New test: conversation in `RECOMMENDATION` state with no DNI captured yet shows the DNI nudge appended to the normal reply.
- [x] 3.6 New test: a message in `RECOMMENDATION` that is only an 8-digit DNI is consumed (no nudge that turn, not fed to qualification extractors).

## 4. Verification

- [x] 4.1 Run the coordinator/identity-gate/lead-creation pytest suite and confirm green.
