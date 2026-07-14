# Step 5 — Manual Endpoint Testing with curl

**Date:** 2026-07-13
**Change:** qualification-dimensions-us-202-205
**Status: BLOCKED — environment cannot open a real DB connection**

## What was attempted

1. Started the backend (`uv run --no-sync uvicorn app.main:app --host 127.0.0.1
   --port 8123`) against the real dev database configured in `.env`
   (`aws-1-us-east-2.pooler.supabase.com:5432/postgres`, Supabase transaction
   pooler).
2. Server log:
   ```
   INFO:     Started server process [20748]
   INFO:     Waiting for application startup.
   OPENSSL_Uplink(...): no OPENSSL_Applink
   ```
   The process crashes (no Python traceback — a native-level crash) during
   startup, before `/healthz` or `/readyz` ever respond.
3. Isolated the crash from app code: a bare `asyncpg.connect(..., ssl="require")`
   against the same `DATABASE_URL`, with no FastAPI/SQLAlchemy involved,
   crashes identically with the same `OPENSSL_Uplink` message and no
   traceback. A plain `SELECT 1` through `app.core.database.get_session_factory()`
   crashes the same way.
4. Confirmed this is unrelated to this change: the crash reproduces on a raw
   asyncpg connection attempt, before any of this change's code runs.

**Root cause (best diagnosis without further environment access):** a known
class of issue where `asyncpg`'s SSL handshake crashes native OpenSSL on
Windows (`OPENSSL_Uplink` errors are a documented Windows-OpenSSL-in-a-thread
problem). This sandbox also has no outbound network to PyPI (confirmed
separately while trying to add `pytest-cov` in Step 4), so it cannot be
resolved here by upgrading `asyncpg`/`cryptography` either.

## What this means for Step 5

The 5 support endpoints (`POST /api/v1/leads/{lead_id}/profile/{budget|
locations|property-type|timeline|must-haves}`) were **not** exercised with
curl against a live server in this environment — the server cannot start
against the real Supabase database here. This is an environment limitation,
not a defect discovered in the endpoint code.

**Mitigating evidence already gathered:**
- `tests/test_qualification_flow.py` and `tests/test_buyer_profile.py`
  exercise the same `BuyerProfileCaptureService.update_profile` write path
  the router calls, against a real (in-memory SQLite) database, including the
  422-equivalent (`ProfileValidationError`) and 404-equivalent
  (`LeadNotFoundError`, via the cross-tenant test) paths — see Step 4 report.
- The router itself (`app/modules/lead_qualification/api/router.py`) is a
  thin, direct translation of validated request DTOs into the same
  `ProfilePatch`/`update_profile` calls already covered by those tests; no
  additional business logic lives in the router beyond ownership
  verification and HTTP status mapping.

**No test data was left behind:** the crash happens before any query
executes (confirmed via the bare `asyncpg.connect` reproduction), so the
scratch setup script (`setup_qa_lead.py`, run outside the repo) never reached
its `session.commit()` — no `organizations`/`leads` rows were written to the
real database.

## Recommendation

Re-run Step 5 in an environment that can open a real connection to the
configured Supabase instance (e.g. Linux/macOS dev machine, or this same
Windows machine with a working asyncpg/OpenSSL install, or Docker) using:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
# then for each dimension:
curl -s -X POST http://127.0.0.1:8000/api/v1/leads/{lead_id}/profile/budget \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"minimum": 100000, "maximum": 150000}'
```

repeating with `locations`, `property-type`, `timeline`, `must-haves`
payloads, an invalid payload per dimension (expect 422), and a
non-existent `lead_id` (expect 404) — then delete the created
`buyer_profiles` row and restore state, per the original task instructions.

**Task 6 (doc update) has NOT been marked "Implementado"** because Step 5
verification is incomplete — see `tasks.md` §6.1, which explicitly requires
leaving the HU rows as "Parcial" if this gap remains open.
