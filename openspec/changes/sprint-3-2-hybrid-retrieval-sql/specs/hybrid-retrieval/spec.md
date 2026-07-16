## ADDED Requirements

### Requirement: Structured filtering runs as SQL WHERE
`StructuredFilterService.filter_candidates` SHALL delegate hard-constraint filtering to a repository query that applies `organization_id` plus the profile's constraints (inclusive price range, zone membership against `district`, property type equality) as a SQL `WHERE` clause, and SHALL NOT load the organization's full catalog into Python for filtering.

#### Scenario: Candidates within budget and zone
- **WHEN** a BuyerProfile with budget, locations, and property_type runs through the filter
- **THEN** the repository query returns only properties matching every hard constraint, filtered by the database

#### Scenario: Absent constraints add no clauses
- **WHEN** the profile has no budget, no locations, or no property_type
- **THEN** the corresponding SQL condition is omitted (same semantics as `Property.matches_hard_filters`)

#### Scenario: Full-catalog load is gone
- **WHEN** `filter_candidates` executes
- **THEN** `list_for_organization` is not called

### Requirement: Semantic retrieval uses pgvector on Postgres
On PostgreSQL, `SemanticRetrievalService.retrieve` SHALL rank the filtered candidates with a single SQL query ordering by the pgvector `<->` cosine-distance operator over `property_embeddings.vector`, honoring `top_n`, and SHALL NOT compute cosine similarity in Python on that path. An HNSW index with `vector_cosine_ops` SHALL exist on `property_embeddings.vector`.

#### Scenario: SQL path selected on Postgres
- **WHEN** the property store supports semantic search (PostgreSQL dialect)
- **THEN** the returned top-N ordering comes from the `<->` query and the in-memory similarity function is never invoked

#### Scenario: HNSW index present
- **WHEN** migration 0013 runs
- **THEN** an HNSW index using `vector_cosine_ops` exists on `property_embeddings.vector`

### Requirement: Portable fallback preserves behavior
On dialects without pgvector (e.g. the SQLite test harness), the system SHALL fall back to the existing in-memory similarity ranking with unchanged behavior, and candidates without a stored embedding SHALL be excluded rather than causing an error on either path.

#### Scenario: SQLite test harness
- **WHEN** `retrieve` runs against a store whose semantic search reports unsupported
- **THEN** the in-memory ranking produces the result exactly as before

#### Scenario: Candidate without embedding
- **WHEN** a filtered candidate has no `property_embeddings` row yet
- **THEN** it is excluded from the semantic ranking on both paths
