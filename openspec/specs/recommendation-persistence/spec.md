## Purpose

Recommendation persistence (US-310, closing backlog US-301) makes every recommendation search auditable: one `recommendations` row per ranked property capturing the exact ranking rationale (`signals` jsonb), the explanation and neighborhood snapshot delivered, and the delivery/feedback lifecycle — written by `RecommendationService` itself so every caller (wiring today, Coordinator later) leaves a trail.

## Requirements

### Requirement: Every ranked search is persisted
`RecommendationService.search()` SHALL persist one `recommendations` row per ranked property before returning, via an optional `recommendation_store` dependency, recording organization_id, lead_id, buyer_profile_id, property_id, rank, score, `signals` jsonb (the ranked candidate's `RankingSignal[]` as `[{"name", "weight", "value"}]`), explanation, `neighborhood` jsonb (nullable), and `generated_at`.

#### Scenario: Search with ranked items persists rows
- **WHEN** `search()` produces N ranked items and a store is configured
- **THEN** N `recommendations` rows are inserted, each with its rank, score, signals, explanation, and neighborhood snapshot

#### Scenario: Empty result persists nothing
- **WHEN** `search()` ranks zero candidates
- **THEN** no `recommendations` row is inserted

#### Scenario: No store configured
- **WHEN** `search()` runs without a `recommendation_store` (e.g. facade unit tests)
- **THEN** the pipeline behaves exactly as before and nothing is persisted

### Requirement: Ranking signals travel with the result
`RecommendationItem` SHALL carry the `RankingSignal` tuple that produced its score, so persistence and future consumers audit the exact ranking rationale.

#### Scenario: Signals present on returned items
- **WHEN** `search()` returns items
- **THEN** each item's `signals` equals the ranked candidate's signals for that property

### Requirement: Delivery lifecycle
The system SHALL record `delivered_at` on a lead's recommendation rows only after the recommendation message was actually published for delivery; `feedback` SHALL remain a nullable jsonb reserved for future feedback events.

#### Scenario: Delivered after ResponseReady
- **WHEN** `wiring.handle_profile_completed` publishes `ResponseReady` for a computed recommendation
- **THEN** the just-persisted rows for that lead get `delivered_at` set

#### Scenario: Computed but not delivered
- **WHEN** a recommendation is computed but no conversation is linked to the lead
- **THEN** its rows keep `delivered_at` NULL

### Requirement: Tenant isolation for recommendations
The `recommendations` table SHALL enforce row-level security by `organization_id`, consistent with the 0004 policy pattern.

#### Scenario: RLS policy present
- **WHEN** migration 0012 runs
- **THEN** RLS is enabled on `recommendations` with the org-isolation policy
