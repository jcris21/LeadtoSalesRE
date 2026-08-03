## Purpose

Affinity profile aggregation (US-211) synthesizes a lead's accumulated `conversation_memory` observations into two independent jsonb snapshots with distinct owners and consumers: `buyer_profiles.ai_profile` (deterministic affinity scores for the Ranking Engine, US-305) and `leads.buyer_persona` (communication/context signals for the Coordinator, AI-104). Recompute happens only when new observations are persisted — never on the recommendation/search read path.

## Requirements

### Requirement: Affinity profile aggregation from conversation memory
The system SHALL provide a `ProfileAggregationService` that synthesizes a lead's `conversation_memory` observations with `confidence >= 0.5` into a deterministic `ai_profile` snapshot persisted in `buyer_profiles.ai_profile`, containing at minimum `modern_score`, `family_score`, `confidence`, `observation_count`, and `computed_at`.

#### Scenario: Sufficient observations accumulated
- **WHEN** a lead has one or more `conversation_memory` rows with `confidence >= 0.5` and the aggregator runs
- **THEN** `buyer_profiles.ai_profile` is updated with a jsonb snapshot containing `modern_score`, `family_score`, `confidence`, `observation_count`, and `computed_at`

#### Scenario: Observations below the confidence threshold are excluded
- **WHEN** a lead has `conversation_memory` rows with `confidence < 0.5`
- **THEN** those rows do not contribute to the `ai_profile` snapshot
- **AND** if no eligible rows remain, no snapshot is written and any existing snapshot is left untouched

#### Scenario: Aggregation is idempotent over an unchanged observation set
- **WHEN** the aggregator runs twice against the same set of `conversation_memory` rows
- **THEN** both runs produce the same scores (`computed_at` provenance aside)

### Requirement: Buyer persona snapshot per lead
The system SHALL derive a `buyer_persona` snapshot persisted in `leads.buyer_persona`, containing communication/context signals (`family_stage`, `has_pets`, `communication`, `computed_at`) mapped deterministically from `family_context` observations, independent of the `ai_profile` snapshot.

#### Scenario: Family context observations produce a persona
- **WHEN** a lead has an eligible `family_context` observation mentioning children
- **THEN** `leads.buyer_persona` is updated with `family_stage = "family_with_children"`

#### Scenario: Pet mention flags the persona
- **WHEN** a lead has an eligible `family_context` observation mentioning a pet
- **THEN** `leads.buyer_persona.has_pets` is `true`

### Requirement: Snapshot independence
The system SHALL keep `ai_profile` and `buyer_persona` strictly independent: writing one MUST NOT modify the other, and neither MUST modify any `PROFILE_DIMENSIONS` field, US-208 dimension (`financing_type`, `decision_maker_mode`), lead scoring field, or `conversation_memory` row.

#### Scenario: Aggregation does not cross-write snapshots
- **WHEN** the aggregator updates `buyer_profiles.ai_profile`
- **THEN** `leads.buyer_persona` retains its prior value unless persona-relevant observations changed, and vice versa

#### Scenario: Aggregation never mutates qualification dimensions
- **WHEN** the aggregator runs for a lead with a populated `BuyerProfile`
- **THEN** `budget_min/max`, `locations`, `property_type`, `timeline`, `must_haves`, `financing_type`, and `decision_maker_mode` are unchanged
- **AND** `conversation_memory` rows are neither updated nor deleted

### Requirement: Recompute only on observation change
The system SHALL recompute snapshots only when new observations are persisted (the aggregator is invoked after `extract_conversation_memory` returns a non-empty result); it SHALL NOT recompute on the recommendation/search read path.

#### Scenario: Extraction with no new signal triggers no aggregation
- **WHEN** `extract_conversation_memory` returns an empty list for a message
- **THEN** the aggregator is not invoked and both snapshots remain unchanged

### Requirement: Graceful degradation without a buyer profile
The system SHALL still write `leads.buyer_persona` when the lead has no `buyer_profiles` row, skipping only the `ai_profile` snapshot, and SHALL NOT create a `BuyerProfile` row as a side effect.

#### Scenario: Lead not yet profiled
- **WHEN** the aggregator runs for a lead with eligible observations but no `buyer_profiles` row
- **THEN** `leads.buyer_persona` is updated
- **AND** no `buyer_profiles` row is created

### Requirement: Tenant isolation for aggregation
The system SHALL verify the lead belongs to the caller's `organization_id` before writing any snapshot, raising `LeadNotFoundError` otherwise.

#### Scenario: Cross-tenant aggregation attempt
- **WHEN** the aggregator is invoked with a `lead_id` belonging to a different organization
- **THEN** `LeadNotFoundError` is raised and no snapshot is written
