## Purpose

The property catalog (US-309) is the local mirror of the inventory source that the Structured Filter queries by plain SQL. Its schema is reconciled across ORM, domain, migrations, and the real database: snake_case `district` (the ORM attribute stays `zone`), plus the formalized `name_address`, `estado`, and `link_references` (jsonb list of media URLs) columns that previously existed only in the hand-edited Supabase schema.

## Requirements

### Requirement: Reconciled properties schema
The system SHALL store property zone data in a snake_case `district` column, and SHALL formalize `name_address` (text, nullable), `estado` (text, nullable), and `link_references` (jsonb list of URLs, default empty) in the `properties` table, the `PropertyORM` model, and the `Property` domain entity, eliminating the drift between ORM and database.

#### Scenario: ORM attribute maps to the reconciled column
- **WHEN** `PropertyORM.zone` is read or written
- **THEN** it maps to the `district` column in the database

#### Scenario: New fields round-trip through the repository
- **WHEN** a `Property` with `name_address`, `estado`, and `link_references` is upserted and re-read
- **THEN** all three values persist and hydrate unchanged, with `link_references` as an ordered list of URL strings

### Requirement: State-conditional reconciliation migration
The reconciliation migration SHALL detect the database's actual state and converge both documented starting states — the fresh 0004 schema (`zone` column) and the manually drifted schema (`District`, `name_address`, `Link_references` text, `estado`) — to the reconciled schema, and its downgrade SHALL restore the 0004 shape.

#### Scenario: Fresh database
- **WHEN** the migration runs against a database created by migration 0004 (has `zone`, none of the drift columns)
- **THEN** `zone` is renamed to `district` and `name_address`, `estado`, `link_references` (jsonb) are added

#### Scenario: Drifted database
- **WHEN** the migration runs against a database with `District` and `Link_references` (text)
- **THEN** `District` is renamed to `district`, `Link_references` becomes `link_references` jsonb (wrapping a bare string value into a one-element array), and columns that already exist are not re-added

### Requirement: Ingestion content hash is stable across reconciliation
The property `content_hash` SHALL keep its existing inputs (external_id, price, zone, property_type, features, description) so the schema reconciliation does not invalidate stored embedding hashes or trigger mass re-embedding.

#### Scenario: Reconciled fields do not change the hash
- **WHEN** a property's `name_address`, `estado`, or `link_references` change but its semantic content does not
- **THEN** `content_hash` is unchanged and no embedding recompute is triggered
