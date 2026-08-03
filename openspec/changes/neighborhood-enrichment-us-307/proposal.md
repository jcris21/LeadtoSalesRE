## Why

US-307 (Neighborhood Enrichment) is marked `Parcial`: `NeighborhoodEnrichmentAdapter` and `GoogleMapsClient` already implement the fan-out/fan-in, timeout, partial-fallback, and late-retry behavior end to end, and persistence to `recommendations.neighborhood` already ships (US-310). But the adapter can never return real data today for two independent reasons: (1) `wiring.py` builds `GoogleMapsClient` with no API key — there is no `google_maps_api_key` setting to read one from — so every real call fails auth; and (2) even with a key, `MapsClient.nearby` is called with `zone=str(property_id)` (a UUID) instead of a real coordinate/address, so Google Places Nearby Search would reject the request with a 400. Both gaps must close before this capability can be marked done.

## What Changes

- Add `google_maps_api_key: str | None = None` to `Settings` (`app/core/config.py`), following the existing optional-credential pattern (`gemini_api_key`, `groq_api_key`): unset means zero network calls, not a crash.
- Wire the configured key into `GoogleMapsClient` construction in `wiring.py._get_enrichment_adapter()`.
- Resolve each property's real location (lat/lng or address) before calling Maps, instead of passing the `property_id` UUID as `zone`. Requires extending the enrichment call path to look up `Property` location data (a new dependency the adapter currently lacks, per its own code comment).
- Update `GoogleMapsClient.nearby` to build the Google Places `location` parameter from real coordinates.
- Distinguish, in logs, "skipped — no API key configured" from "Maps call failed/timed out" (currently both fall into one generic `except Exception` branch).
- Skip the outbound HTTP call entirely when no API key is configured (avoid guaranteed-401 network calls).
- Update `Documents/Oficial/HU_Calificacion_Recomendacion.md` (US-307 status `Parcial` → `Sí`, correct the stale "no tabla propia" note) and `.env.example` (document `GOOGLE_MAPS_API_KEY`).

## Capabilities

### New Capabilities
- `neighborhood-enrichment`: fan-out/fan-in Google Maps enrichment of the Top-3 recommended properties, with per-property timeout, partial fallback (`neighborhood=None`), bounded background retry publishing `NeighborhoodEnriched`, and now real API-key wiring + real location resolution (previously stubbed/unwired).

### Modified Capabilities
(none — `recommendation-persistence` already persists the `neighborhood` jsonb snapshot and is unaffected; this change only fixes what feeds that snapshot)

## Impact

- `app/core/config.py` — new `Settings` field.
- `app/modules/recommendation/wiring.py` — pass API key to `GoogleMapsClient`.
- `app/modules/recommendation/infrastructure/maps_client.py` — `nearby()` builds a real `location` param.
- `app/modules/recommendation/application/neighborhood_enrichment.py` — `enrich_top3` gains a property-location lookup dependency; skip Maps call when no key configured.
- `app/modules/recommendation/domain/ports.py` — `NeighborhoodEnrichmentPort` signature may need to accept location data (or a lookup dependency) alongside `property_id`s.
- Tests: `tests/test_neighborhood_enrichment.py`, `tests/test_recommendation_wiring.py`.
- Docs: `Documents/Oficial/HU_Calificacion_Recomendacion.md`, `.env.example`.
- No breaking changes; no DB schema changes (persistence already supports the `neighborhood` jsonb column).
