## Context

`NeighborhoodEnrichmentAdapter` (`app/modules/recommendation/application/neighborhood_enrichment.py`) and `GoogleMapsClient` (`app/modules/recommendation/infrastructure/maps_client.py`) already implement the full fan-out/fan-in, timeout, partial-fallback, and background-retry behavior described in Architecture.md §7.10-§7.12. Two things were explicitly deferred when that code was written:

1. No Google Maps API key wiring existed in `Settings` (`app/core/config.py`) — `wiring.py._get_enrichment_adapter()` constructs `GoogleMapsClient(httpx.AsyncClient())` with the default `api_key=""`.
2. `NeighborhoodEnrichmentPort.enrich_top3` only carries `property_id`s (`domain/ports.py`), not each property's zone/coordinates — the adapter's own docstring says resolving a property to its zone is "out of scope for this sprint... a follow-up once a `Property` repository is passed in here." Today `MapsClient.nearby` is called with `zone=str(property_id)`, a UUID, which Google Places Nearby Search would reject.

Persistence of the resulting `NeighborhoodInsight` into `recommendations.neighborhood` (jsonb) is already implemented (US-310, `repository.py`) and is out of scope here.

## Goals / Non-Goals

**Goals:**
- Make a real Google Maps API key configurable via `Settings`, following the same optional-credential convention as `gemini_api_key`/`groq_api_key` (unset → zero network calls, no crash).
- Resolve each property's real location (lat/lng, falling back to address if coordinates are absent) before calling Maps, replacing the `property_id`-as-`zone` placeholder.
- Keep the fan-out/fan-in, timeout, partial-fallback, and background-retry behavior in `NeighborhoodEnrichmentAdapter` unchanged — this change only fixes what feeds it.
- Make "no API key configured" observably distinct from "Maps call failed/timed out" in logs.

**Non-Goals:**
- Changing the persistence layer (`recommendations.neighborhood` jsonb) — already correct.
- Changing the timeout/retry budget or the outbox/event contract (`NeighborhoodEnriched`).
- Building a full geocoding pipeline — properties are assumed to already carry (or can look up) lat/lng; if not, this change adds the minimal lookup needed, not a new geocoding service.

## Decisions

**1. `google_maps_api_key` as an optional `Settings` field, not required.**
Alternative considered: require the key so misconfiguration fails fast at startup. Rejected — matches the existing pattern for `gemini_api_key`/`groq_api_key`: local/dev/test environments must keep working with zero external credentials, and enrichment is explicitly best-effort/non-blocking per the original US-307 acceptance criteria. A missing key degrades to `neighborhood=None` for every property, which is already a documented, expected, and tested outcome.

**2. Skip the HTTP call entirely when no key is configured, rather than calling and letting it fail.**
Alternative considered: always call, let auth failures flow through the existing `except Exception` fallback path (already handled). Rejected as the sole behavior — calling Google with an empty key on every enrichment in keyless environments (all of local dev/CI today) is wasted network I/O and noisy logs at scale (Top-3 × every recommendation search). Short-circuiting when the key is absent is strictly better and requires no change to the adapter's external contract.

**3. Resolve location via a new lookup dependency injected into the adapter, not by widening the port's `property_id` list into inline location tuples.**
Alternative considered: change `enrich_top3`'s signature to accept `list[tuple[uuid.UUID, float, float]]` instead of `list[uuid.UUID]`. Rejected — that pushes location-resolution responsibility onto every caller of `NeighborhoodEnrichmentPort` (currently just `RecommendationService`/wiring), duplicating a lookup that belongs next to the adapter. Instead, inject a narrow `PropertyLocationPort` (or reuse the existing property repository) into `NeighborhoodEnrichmentAdapter`'s constructor; `enrich_top3` keeps its existing `property_id`-list signature so the `RecommendationPort` facade contract is untouched.

**4. Distinguish "no key" vs "call failed" via a dedicated early-return branch, not by inspecting exception types.**
The no-key case is checked once per `enrich_top3` call (not per-property, since the key is global), logged once at `info` level, and every property short-circuits to `None` without entering the network path. The existing generic `except Exception` in `fetch_one`/`_retry_and_publish` remains the catch-all for genuine Maps failures/timeouts and keeps its current log message.

## Risks / Trade-offs

- [Risk] Property location data may not exist for all rows (e.g., legacy rows from the `properties` schema reconciliation, US-309) → Mitigation: location lookup returns `None` for properties without coordinates; adapter treats "no location" the same as "no key" — skip the call, return `neighborhood=None`, no exception raised.
- [Risk] Adding a location-lookup dependency to `NeighborhoodEnrichmentAdapter`'s constructor changes its wiring signature → Mitigation: default the dependency to `None`/a no-op lookup in the constructor so existing tests using `FakeMapsClient` without a location lookup continue to pass unchanged; only real wiring (`wiring.py`) needs updating.
- [Risk] Google Places Nearby Search billing/quota once a real key is set → Mitigation: out of scope for this change (ops concern); the existing per-property timeout and bounded retry (`max_retries=1`) already cap worst-case call volume per lead.

## Migration Plan

1. Add `google_maps_api_key` to `Settings`; no migration needed (optional field, defaults to `None`).
2. Add property-location lookup dependency to the adapter; wire it in `wiring.py` alongside the API key.
3. Update `.env.example` and HU documentation.
4. Deploy: no schema change, no rollback complexity — absent the env var, behavior is identical to today (degrades to `neighborhood=None`).

## Open Questions

- Which field(s) on `Property`/`PropertyORM` currently hold coordinates, if any? If none exist yet, this change may need to add a minimal lat/lng (or geocode-on-read) capability — needs a look at `app/modules/recommendation/domain/models.py::Property` and `PropertyORM` during implementation (tasks.md should include a verification step before assuming the field exists).
