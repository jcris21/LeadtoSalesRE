## 1. Config & wiring

- [x] 1.1 Add `google_maps_api_key: str | None = None` to `Settings` (`app/core/config.py`), following the `gemini_api_key`/`groq_api_key` convention (comment explaining optional, no-network-if-unset behavior).
- [x] 1.2 Update `.env.example` (or equivalent) to document `GOOGLE_MAPS_API_KEY`.
- [x] 1.3 Update `wiring.py._get_enrichment_adapter()` to pass `get_settings().google_maps_api_key or ""` into `GoogleMapsClient`.

## 2. Location resolution

- [x] 2.1 Verify what location data `Property`/`PropertyORM` currently expose (`zone`, `name_address`) — confirm via `app/modules/recommendation/domain/models.py` and repository/ORM before assuming a field name.
- [x] 2.2 Add a narrow location-lookup dependency (e.g. `PropertyLocationPort` or reuse the existing property repository) that `NeighborhoodEnrichmentAdapter` can call to resolve a `property_id` to its real `zone`/`name_address`. Default to `None`/no-op in the constructor so existing tests without this dependency keep passing.
- [x] 2.3 Update `NeighborhoodEnrichmentAdapter.enrich_top3`/`fetch_one`/`_retry_and_publish` to resolve location first, and pass it (not `property_id`) as `MapsClient.nearby`'s location argument.
- [x] 2.4 Update `GoogleMapsClient.nearby` to build the Google Places `location` request parameter from the resolved location.
- [x] 2.5 When location resolution returns nothing for a property, skip the Maps call for that property and resolve it to `neighborhood=None`, matching the no-API-key path.
- [x] 2.6 Wire the real property-location lookup into `wiring.py` alongside the API key.

## 3. Skip-when-unconfigured behavior & observability

- [x] 3.1 In `enrich_top3`, short-circuit (no HTTP call) for every property when `google_maps_api_key` is unset; log once at `info` level that enrichment was skipped for lack of a configured key.
- [x] 3.2 Keep the existing generic `except Exception` fallback in `fetch_one`/`_retry_and_publish` for genuine Maps failures/timeouts, with its current log message unchanged, so it stays distinguishable from the "no key" skip path.

## 4. Tests

- [x] 4.1 `tests/test_neighborhood_enrichment.py`: add a case asserting no HTTP call is attempted and all properties resolve to `None` when no API key is configured.
- [x] 4.2 `tests/test_neighborhood_enrichment.py`: add a case asserting `MapsClient.nearby` receives the property's real resolved location, not its `property_id`.
- [x] 4.3 `tests/test_neighborhood_enrichment.py`: add a case for a property with no resolvable location — skipped, resolves to `None`, siblings unaffected.
- [x] 4.4 Confirm existing fan-out/fan-in, timeout, partial-fallback, and background-retry tests (`FakeMapsClient`-based) still pass unchanged.
- [x] 4.5 `tests/test_recommendation_wiring.py`: assert `_get_enrichment_adapter()` wires the configured API key and location lookup into `GoogleMapsClient`/`NeighborhoodEnrichmentAdapter`.

## 5. Documentation

- [x] 5.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md`: US-307 status `Parcial` → `Sí`, correct the stale "(c) Ninguna tabla propia hoy" note (persistence already ships via US-310), update "(d)" to reflect API key + real location wiring.
- [x] 5.2 Update the capability status table row for US-307 (line ~612) to `Sí`.
