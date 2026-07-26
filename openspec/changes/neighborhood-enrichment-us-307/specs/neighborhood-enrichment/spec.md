## ADDED Requirements

### Requirement: Google Maps API key is configurable and optional
The system SHALL expose a `google_maps_api_key` setting (`Settings.google_maps_api_key: str | None`, default `None`) that `NeighborhoodEnrichmentAdapter`'s Maps client is constructed with. When unset, the adapter SHALL make zero outbound HTTP calls to Google Maps and SHALL NOT raise — every property resolves to `neighborhood=None`, matching the existing best-effort/non-blocking contract of `enrich_top3`.

#### Scenario: No API key configured
- **WHEN** `enrich_top3` is called and `Settings.google_maps_api_key` is `None`
- **THEN** no HTTP request is made to Google Maps for any property
- **AND** every property in the result maps to `None`
- **AND** a single `info`-level log line records that enrichment was skipped for lack of a configured key (not a per-property warning/error)

#### Scenario: API key configured
- **WHEN** `Settings.google_maps_api_key` is set to a non-empty string
- **THEN** `GoogleMapsClient` is constructed with that key and used for real Nearby Search calls

### Requirement: Enrichment resolves each property's real location before calling Maps
The system SHALL resolve each property's real location (its `zone`/`name_address`, per `Property` domain model) before calling `MapsClient.nearby`, rather than passing the property's `property_id` UUID as the location parameter. Properties with no resolvable location SHALL be treated the same as a missing API key: skipped without a network call, resolving to `neighborhood=None`.

#### Scenario: Property has a resolvable location
- **WHEN** `enrich_top3` runs for a property whose `zone`/`name_address` is present
- **THEN** `MapsClient.nearby` is invoked with that property's real location, not its `property_id`

#### Scenario: Property has no resolvable location
- **WHEN** `enrich_top3` runs for a property with no `zone`/`name_address` on record
- **THEN** no Maps call is made for that property
- **AND** that property resolves to `neighborhood=None`
- **AND** the property's timeout/fallback/retry behavior for every other property in the same batch is unaffected

### Requirement: Existing fan-out/fan-in, timeout, and retry behavior is preserved
The system SHALL preserve `NeighborhoodEnrichmentAdapter`'s existing behavior unchanged: parallel fan-out across the Top-3 properties, a per-property timeout that falls back to `neighborhood=None` without blocking sibling lookups, and a bounded background retry that publishes `NeighborhoodEnriched` on eventual success. The API-key and location-resolution changes SHALL NOT alter this contract or the `NeighborhoodEnrichmentPort.enrich_top3` signature.

#### Scenario: Real Maps call times out
- **WHEN** a property has a valid API key and a resolvable location, but the Maps call exceeds `timeout_ms`
- **THEN** that property resolves to `neighborhood=None` in the immediate result
- **AND** a bounded background retry is scheduled that publishes `NeighborhoodEnriched` if it later succeeds
- **AND** sibling properties in the same batch are unaffected by the timeout

#### Scenario: Maps call fails (not a timeout)
- **WHEN** a property has a valid API key and location, but the Maps call raises an error (e.g., non-2xx response)
- **THEN** that property resolves to `neighborhood=None`
- **AND** the failure is logged distinctly from the "no API key configured" case
