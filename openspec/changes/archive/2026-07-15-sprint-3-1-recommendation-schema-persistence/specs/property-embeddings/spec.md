## ADDED Requirements

### Requirement: Real embedding model behind the async seam
The system SHALL provide an `OpenAIEmbeddingModel` implementing the `EmbeddingModel` protocol that generates 1536-dimension vectors via OpenAI `text-embedding-3-small` from the property's semantic content, with `model_version = "text-embedding-3-small"`. The `EmbeddingModel.embed` seam SHALL be asynchronous.

#### Scenario: Real embedding generated for a property
- **WHEN** the ingestion pipeline embeds a property with the real model configured
- **THEN** a 1536-float vector is produced and persisted in `property_embeddings` with `model_version = "text-embedding-3-small"`

#### Scenario: Transient API failure is retried once
- **WHEN** the embeddings API responds 429 or 5xx
- **THEN** the call is retried once, and if it fails again the error propagates (no stale or partial vector is stored)

### Requirement: Hermetic fallback without an API key
The system SHALL select the embedding model by configuration: `OpenAIEmbeddingModel` when `openai_api_key` is set, otherwise the deterministic `HashEmbeddingModel` with a logged warning. Tests and keyless environments SHALL make no network calls.

#### Scenario: No API key configured
- **WHEN** the ingestion wiring initializes with `openai_api_key` unset
- **THEN** `HashEmbeddingModel` is used and a warning is logged

### Requirement: vector(1536) storage on Postgres
The migration SHALL enable the pgvector extension and convert `property_embeddings.vector` to `vector(1536)` on Postgres, discarding obsolete `hash-v1` stand-in rows (derived data, recomputed by hash-gated ingestion). The ORM column type SHALL remain portable JSON until US-304 introduces typed retrieval.

#### Scenario: Column converted and stand-ins discarded
- **WHEN** migration 0011 runs
- **THEN** the `vector` extension exists, rows with `model_version = 'hash-v1'` are deleted, and `property_embeddings.vector` is of type `vector(1536)`

#### Scenario: Recompute only on content change still holds
- **WHEN** a property's content hash is unchanged since its last embedding
- **THEN** no embedding call is made regardless of which model is configured
