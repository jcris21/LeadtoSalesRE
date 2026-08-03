## MODIFIED Requirements

### Requirement: Structured filtering runs as SQL WHERE
`StructuredFilterService.filter_candidates` SHALL delegate hard-constraint filtering to a repository query that applies `organization_id` plus the profile's constraints (inclusive price range, zone membership against `district`, property type equality, bedroom count equality against `properties.bedrooms`) as a SQL `WHERE` clause, and SHALL NOT load the organization's full catalog into Python for filtering.

#### Scenario: Candidates within budget and zone
- **WHEN** a BuyerProfile with budget, locations, and property_type runs through the filter
- **THEN** the repository query returns only properties matching every hard constraint, filtered by the database

#### Scenario: Candidates matching bedroom count
- **WHEN** a BuyerProfile with `bedrooms` set runs through the filter
- **THEN** the repository query returns only properties whose `properties.bedrooms` equals the profile's `bedrooms` value, and properties with `bedrooms IS NULL` are excluded

#### Scenario: Absent constraints add no clauses
- **WHEN** the profile has no budget, no locations, no property_type, or no bedrooms
- **THEN** the corresponding SQL condition is omitted (same semantics as `Property.matches_hard_filters`)

#### Scenario: Full-catalog load is gone
- **WHEN** `filter_candidates` executes
- **THEN** `list_for_organization` is not called
