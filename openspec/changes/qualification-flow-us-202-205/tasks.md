## 1. Verify the existing conversational entry point (no code expected)

- [x] 1.1 Confirm `CoordinatorAgent.handle_message` calls `run_qualification_turn` on every turn with a linked lead (`app/modules/conversation_ownership/application/coordinator.py`)
- [x] 1.2 Confirm `run_qualification_turn` invokes the four US-202–US-205 extractors plus the US-208/US-209 ones and persists via `BuyerProfileCaptureService.update_profile`
- [x] 1.3 Confirm `tests/test_coordinator_qualification_turn.py::test_e2e_script_fills_profile_and_fires_profile_completed` exercises budget, locations, property_type, timeline, must_haves purely through chat messages and asserts `ProfileCompleted` fires exactly once

## 2. Close the must_haves deduplication gap

- [x] 2.1 Add case/whitespace-insensitive, order-preserving deduplication of `must_haves` items in `_extract_must_haves` (`app/modules/lead_qualification/application/qualification_flow.py`)
- [x] 2.2 Add a test asserting a message with a duplicated requirement (e.g. "cochera, Cochera y balcón") persists `("cochera", "balcón")`
- [x] 2.3 (found during 3.1, not originally scoped) `_RANGE_RE`/`_SINGLE_RE` did NOT tolerate a currency symbol/word directly before the second number in a range (e.g. "$100,000 y $150,000" failed to match as a range) — fixed by adding an optional `_CURRENCY_PREFIX` before each amount group; single-amount and range-without-currency behavior unchanged (verified by the full `qualification_flow` test file)

## 3. Add missing test coverage

- [x] 3.1 Add budget tests: single amount with currency word ("150000 dólares"), range with currency symbol ("$100,000 y $150,000"), range with "S/ ... soles"
- [x] 3.2 Add a test proving `timeline` captured in a later turn does not erase `must_haves` captured in an earlier turn (and vice versa)
- [x] 3.3 Add a `ProfileValidationError`-to-reprompt test for budget at the `qualification_flow.py` unit level (min <= 0), complementing the existing coordinator-level `test_invalid_budget_signal_reprompts_instead_of_template`
- [x] 3.4 Add a property_type ambiguous-input test asserting the documented "captures first mention" behavior when two types are mentioned in one message (extends the existing `test_extract_property_type_two_mentions_captures_first` coverage with a distinct phrasing)

## 4. Documentation

- [x] 4.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md` rows for US-202, US-203, US-204, US-205 (summary table + detailed Alineación sections): status `Parcial` -> `Implementado`, Alineación (b) column updated to name the real conversational entry point
- [x] 4.2 Cross-reference this change (`qualification-flow-us-202-205`) from the updated HU rows

## 5. Verification

- [x] 5.1 Run `pytest tests/test_qualification_flow.py tests/test_coordinator_qualification_turn.py tests/test_buyer_profile.py -q` — 39 passed
- [x] 5.2 Run the full `pytest` suite and confirm no regressions — 350 passed, 1 skipped
- [x] 5.3 `openspec validate qualification-flow-us-202-205 --strict` — valid
