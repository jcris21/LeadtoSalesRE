## ADDED Requirements

### Requirement: Qualification Flow is reachable from the real conversational turn
The four Prompt Chaining extractors for budget, locations, property_type, and timeline/must_haves (`app/modules/lead_qualification/application/qualification_flow.py`) SHALL be invoked by `CoordinatorAgent.handle_message` on every conversational turn where the `Conversation` has a linked `Lead`, via `run_qualification_turn` (`qualification_turn.py`) — not only from the QA/support REST endpoints. This is the entry point that makes US-202–US-205 "Implementado" rather than "Parcial".

#### Scenario: A chat-only conversation reaches full profile completeness
- **WHEN** a lead exchanges a sequence of WhatsApp-style messages carrying budget, locations, property_type, timeline, and must_haves signals, with no call to any `/api/v1/leads/{lead_id}/profile/*` endpoint
- **THEN** `BuyerProfile.completeness()` for that lead reaches the configured threshold
- **AND** exactly one `ProfileCompleted` event is emitted, on the turn that crosses the threshold

#### Scenario: A message with no dimension signal does not call update_profile
- **WHEN** a lead's message carries no recognizable budget/locations/property_type/timeline/must_haves signal
- **THEN** no extractor calls `BuyerProfileCaptureService.update_profile` for that message
- **AND** the conversational reply still happens normally

### Requirement: must_haves deduplicates within a single message
`extract_timeline_and_must_haves` SHALL deduplicate the `must_haves` items extracted from one message before building the `ProfilePatch`, comparing items case-insensitively and ignoring leading/trailing whitespace, while preserving the first-seen casing and original order.

#### Scenario: Duplicate requirement mentioned twice in one message
- **WHEN** a lead's message is "Es indispensable que tenga cochera, Cochera y balcón"
- **THEN** the resulting `ProfilePatch.must_haves` contains `("cochera", "balcón")`, not `("cochera", "Cochera", "balcón")`

### Requirement: Budget extraction ignores currency tokens around the amount
`extract_budget` SHALL correctly extract the numeric minimum/maximum from a message regardless of currency symbols or words (e.g. `$`, `USD`, `dólares`, `S/`, `soles`) appearing adjacent to the digits, since the domain (`MoneyRange`) stores amounts without a currency field (Sprint-2 scope decision).

#### Scenario: Single amount with a currency word
- **WHEN** a lead's message is "Tengo un presupuesto de 150000 dólares"
- **THEN** `ProfilePatch.budget` is `MoneyRange(minimum=150000.0, maximum=150000.0)`

#### Scenario: Range with a currency symbol
- **WHEN** a lead's message is "Mi presupuesto es entre $100,000 y $150,000"
- **THEN** `ProfilePatch.budget` is `MoneyRange(minimum=100000.0, maximum=150000.0)`

### Requirement: timeline and must_haves are independently persisted across turns
When `timeline` and `must_haves` are captured in separate conversational turns, capturing one SHALL NOT erase or overwrite the other's already-persisted value, consistent with `BuyerProfile.apply`'s `None`-means-"do not touch" semantics.

#### Scenario: timeline captured after must_haves in an earlier turn
- **GIVEN** a `BuyerProfile` with `must_haves=("cochera",)` already persisted from a prior turn
- **WHEN** a later message captures only `timeline` (e.g. "Quiero comprar en 6 meses")
- **THEN** `BuyerProfile.timeline` is set
- **AND** `BuyerProfile.must_haves` remains `("cochera",)`
