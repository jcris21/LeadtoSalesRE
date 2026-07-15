## ADDED Requirements

### Requirement: Objection detection during Discovery and Recommendation
The system SHALL detect sales objections (types: Precio, Zona, Financiamiento, Tamaño, Tiempo) from a lead's free-text conversational message via deterministic Spanish keyword matching, while the Conversation is in the Discovery or Recommendation state, and SHALL persist each detection as a new row in `lead_objections` (never overwriting a previous detection).

#### Scenario: Price objection detected
- **WHEN** a lead sends a message containing price-resistance keywords (e.g. "está muy caro", "no tengo ese presupuesto") while Conversation State is Discovery or Recommendation
- **THEN** a new `lead_objections` row is inserted with `type=Precio`, the raw message text, `lead_id`, and `organization_id`

#### Scenario: No objection keywords present
- **WHEN** a lead's message contains no recognizable objection keyword for any of the five types
- **THEN** no `lead_objections` row is inserted and `Lead.lead_score`/`lead_classification` are left unchanged

#### Scenario: Cross-tenant objection write is rejected
- **WHEN** an objection is detected for a `lead_id` that does not belong to the caller's `organization_id`
- **THEN** the extractor raises `LeadNotFoundError` and no row is persisted

### Requirement: Hot/Warm/Cold lead classification
The system SHALL maintain a `Lead.lead_classification` value (`Hot`, `Warm`, or `Cold`) derived from `Lead.lead_score`, and SHALL recompute both `lead_score` and `lead_classification` synchronously whenever a new objection is recorded for that lead, using the rule: `lead_score = max(0, 100 - 15 * distinct_objection_types - 5 * total_objection_count)`, with `lead_score >= 70` mapping to Hot, `40 <= lead_score < 70` mapping to Warm, and `lead_score < 40` mapping to Cold.

#### Scenario: Classification recomputed on objection recording
- **GIVEN** a Lead with no prior objections (`lead_score=100.0`, `lead_classification=Hot`)
- **WHEN** an Objection of type Zona is recorded for that Lead
- **THEN** `lead_score` becomes `80.0` (100 - 15*1 - 5*1) and `lead_classification` remains `Hot`

#### Scenario: Lead crosses into Cold after multiple distinct objections
- **GIVEN** a Lead that has already raised 2 distinct objection types (3 total objections raised)
- **WHEN** a 3rd distinct objection type is recorded (4th objection overall)
- **THEN** `lead_score` becomes `100 - 15*3 - 5*4 = 35.0` and `lead_classification` becomes `Cold`

#### Scenario: New lead defaults to Hot
- **WHEN** a `Lead` is created with no objections yet recorded
- **THEN** `lead_classification` defaults to `Hot`
