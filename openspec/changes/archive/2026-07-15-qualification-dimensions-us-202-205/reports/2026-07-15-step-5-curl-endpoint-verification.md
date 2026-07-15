# Step 5 — Manual Endpoint Testing with curl (resolved)

**Date:** 2026-07-15
**Change:** qualification-dimensions-us-202-205
**Status: DONE**

## Root cause of the prior blocker (2026-07-13 report)

The `.venv`'s Python interpreter (a `uv`-managed `cpython-3.12.11-windows-x86_64-none`
standalone build) had a broken OpenSSL: **any** TLS connection — not just
`asyncpg` — crashed the process natively with `OPENSSL_Uplink(...): no
OPENSSL_Applink`, confirmed by reproducing the same crash on a bare
`urllib.request.urlopen("https://...")` call with no database or app code
involved. This is a known class of bug in some `python-build-standalone`
Windows builds. This sandbox has no outbound network to fetch a newer
standalone build (`uv python install` failed with a TLS `UnknownIssuer`
error, same underlying cause).

**Fix:** the machine also has a `python.org`-installed `Python 3.12.2`
(`C:\Users\ASUS\AppData\Local\Programs\Python\Python312\python.exe`) with a
working OpenSSL. Rebuilt `.venv` against that interpreter:

```bash
rm -rf .venv
uv venv --python "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\python.exe"
uv sync --offline   # all deps were already in uv's local cache
```

Verified: `ssl`/`urllib` HTTPS works, a raw `asyncpg.connect(...)` against the
real Supabase `DATABASE_URL` succeeds, and the full test suite still passes
(`155 passed`). This is a local dev-environment fix only — no repository
files were touched.

## Setup

1. Started the backend against the real dev database (`.env` `DATABASE_URL`,
   Supabase transaction pooler) — starts cleanly now:
   `uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8123`.
2. Created two temporary `organizations` rows and one `leads` row each (one
   "target" org/lead used for the valid/invalid/happy-path calls, one "other
   tenant" org/lead reserved for cross-tenant checks — the cross-tenant
   rejection path itself is already covered by an automated test per task
   3.4, so it wasn't re-exercised manually here).
3. Minted a JWT for the target org via `create_access_token` (auth only
   decodes the JWT — no `admin_users` DB lookup — so no user row was needed).

## curl results — all 5 dimensions x {valid, invalid, non-existent lead}

```
=== budget: valid (expect 200) ===
{"completeness":20.0,"captured_dimensions":["budget"]}
HTTP 200

=== budget: invalid (min>max, expect 422) ===
{"detail":"Budget minimum cannot exceed maximum"}
HTTP 422

=== budget: non-existent lead (expect 404) ===
{"detail":"Lead not found"}
HTTP 404

=== locations: valid (expect 200) ===
{"completeness":40.0,"captured_dimensions":["budget","locations"]}
HTTP 200

=== locations: invalid (empty list, expect 422) ===
{"detail":[{"type":"too_short","loc":["body","locations"],"msg":"List should have at least 1 item after validation, not 0","input":[],"ctx":{"field_type":"List","min_length":1,"actual_length":0}}]}
HTTP 422

=== locations: non-existent lead (expect 404) ===
{"detail":"Lead not found"}
HTTP 404

=== property-type: valid (expect 200) ===
{"completeness":60.0,"captured_dimensions":["budget","locations","property_type"]}
HTTP 200

=== property-type: invalid enum (expect 422) ===
{"detail":[{"type":"enum","loc":["body","property_type"],"msg":"Input should be 'apartment', 'house', 'land', 'commercial' or 'other'","input":"spaceship","ctx":{"expected":"'apartment', 'house', 'land', 'commercial' or 'other'"}}]}
HTTP 422

=== property-type: non-existent lead (expect 404) ===
{"detail":"Lead not found"}
HTTP 404

=== timeline: valid (expect 200) ===
{"completeness":80.0,"captured_dimensions":["budget","locations","property_type","timeline"]}
HTTP 200

=== timeline: invalid enum (expect 422) ===
{"detail":[{"type":"enum","loc":["body","timeline"],"msg":"Input should be 'immediate', '3_months', '6_months', 'over_6_months' or 'exploring'","input":"yesterday","ctx":{"expected":"'immediate', '3_months', '6_months', 'over_6_months' or 'exploring'"}}]}
HTTP 422

=== timeline: non-existent lead (expect 404) ===
{"detail":"Lead not found"}
HTTP 404

=== must-haves: valid (expect 200) ===
{"completeness":100.0,"captured_dimensions":["budget","locations","property_type","timeline","must_haves"]}
HTTP 200

=== must-haves: invalid (empty list, expect 422) ===
{"detail":[{"type":"too_short","loc":["body","must_haves"],"msg":"List should have at least 1 item after validation, not 0","input":[],"ctx":{"field_type":"List","min_length":1,"actual_length":0}}]}
HTTP 422

=== must-haves: non-existent lead (expect 404) ===
{"detail":"Lead not found"}
HTTP 404
```

`completeness` climbs 20 -> 40 -> 60 -> 80 -> 100 as each of the 5 dimensions
is captured in sequence, and `captured_dimensions` accumulates correctly —
confirms `BuyerProfileCaptureService.update_profile` and the completeness
calculation work end-to-end through the real router, real auth dependency,
and real Postgres database.

## Cleanup / database state verification

After the run, deleted the temporary `buyer_profiles`, `leads`, and
`organizations` rows (both the target and other-tenant orgs) by id. Verified
afterward with a query scoped to those same ids:

```
orgs remaining: 0
leads remaining: 0
buyer_profiles remaining: 0
```

No other database state was touched. The local server process was stopped
after verification.

## Task 6 status

Step 5 is now fully verified end-to-end (not just via unit tests). This
closes the environment blocker, but does **not** change the
`Documents/Oficial/HU_Calificacion_Recomendacion.md` rows to "Implementado":
per `design.md`, that status requires AI-104 (Coordinator Agent) to route a
real conversation turn into `qualification_flow.py`'s extractors — that
routing does not exist yet (the extractors are unreferenced outside their own
tests; the REST router builds `ProfilePatch` directly from request DTOs, not
via the extractors). Rows correctly stay "Parcial" until that separate,
not-yet-started change lands.
