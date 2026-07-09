# Point the app at real wacrm — add a `deals` API to the fork, wire per-org credentials

## Context

The app currently syncs leads/pipeline against `mocks/wacrm_mock`, a stand-in for wacrm (CON-2: wacrm is System of Record for leads/pipeline). We forked the real wacrm (`github.com/jcris21/wacrm`, cloned to `E:\FILES 2026\MVP_VIBECODE+AGENTIC\wacrm`) to see its real UI and use it as the actual CRM. Investigation found real wacrm's public API (`/api/v1`) only covers messages/contacts/conversations/broadcasts — **no deals/pipeline endpoint exists**, which is the one thing our CDC sync needs. We chose option (b): add a `deals` resource to our fork rather than faking pipeline stage via contact tags, because only the real `deals`/`pipeline_stages` tables are wacrm's actual source of truth for stage — tags would silently diverge from what brokers see on the Kanban board.

Two repos change:
- **wacrm fork** — add the missing `deals` API (list/get/patch), matching its existing `contacts` API conventions exactly.
- **This app** — `wacrm_client.py` currently has zero auth and talks to the mock's `/leads` shape; it needs to call the new `/deals` shape with a per-organization API key. The per-org credential model (`OrganizationConfig.crm: CrmConfig`) already exists in this codebase but was never wired into `WacrmClient` construction (the app has always used one global mock URL) — that wiring gap is why this is more than a one-line URL swap.

Non-goals: no deal *creation* from our app (deals are created by brokers in wacrm's UI — matches CON-2, our app only reads and pushes stage updates back); no changes to `mocks/wacrm_mock` (it stays available for local/offline dev but will no longer match the real shape — flagged as a known, accepted divergence, not silently patched); no deal-change webhook events (out of scope, larger feature).

## Part A — wacrm fork: add the `deals` API

Repo: `E:\FILES 2026\MVP_VIBECODE+AGENTIC\wacrm`. Follow the `contacts` resource as the template throughout (`src/app/api/v1/contacts/route.ts`, `contacts/[id]/route.ts`, `src/lib/api/v1/contacts.ts`).

1. **`src/lib/api-keys/scopes.ts`** — add to `API_SCOPES` + `SCOPE_DESCRIPTIONS`:
   - `deals:read` — "List and read deals"
   - `deals:write` — "Update a deal's stage or assignment"

2. **`src/lib/api/v1/deals.ts`** (new, mirrors `contacts.ts`):
   - `DEAL_SELECT` embed string pulling `pipeline_stages(id, name)`, `contacts(id, phone)`, `assigned_to:profiles(id, full_name, email)`.
   - `serializeDeal(row)` → wire shape: `{ id, account_id, pipeline_stage: stage.name, stage_id, contact_reference: contact.phone, assigned_broker_id: profile?.id ?? null, status, value, currency, updated_at, created_at }`.
   - `getDealById(db, accountId, id)` — `.eq('id', id).eq('account_id', accountId).maybeSingle()`.
   - `resolveStageIdByName(db, pipelineId, stageName)` — looks up `pipeline_stages` scoped to the deal's own `pipeline_id`; throws `DealError('bad_request', ...)` if no match. This is the enforcement point for the stage-naming contract (Part C).
   - `DealError extends Error { status }`.

3. **`src/app/api/v1/deals/route.ts`** (new) — `GET` only, scope `deals:read`:
   - Reuse `parseListParams`/`keysetFilter`/`buildPage` from `src/lib/api/v1/pagination.ts` for the existing keyset pagination.
   - Add **new** optional `?updated_since=<ISO8601>` → `.gte('updated_at', value)`. No timestamp filter exists anywhere in this codebase today — this is net-new, needed for CDC polling.
   - Add **new** optional `?contact_phone=<E.164>` → inner-join filter on `contacts.phone`, same pattern as the existing `?tag=` inner-join in `contacts/route.ts`.

4. **`src/app/api/v1/deals/[id]/route.ts`** (new), mirrors `contacts/[id]/route.ts`:
   - `GET` (scope `deals:read`) — `getDealById`, 404 via `fail('not_found', ...)` if missing.
   - `PATCH` (scope `deals:write`) — partial update, only fields present in the body: `stage_name` (resolved via `resolveStageIdByName` against the deal's existing `pipeline_id`, then writes `stage_id`) and/or `assigned_broker_id` (validate the profile belongs to the same account, or `null` to unassign). Set `updated_at`. Re-fetch and return serialized deal. Catch `DealError` → `bad_request`/`internal` per its `.status`, same as `ContactError` handling today.

5. **`docs/public-api.md`** — add `### GET /api/v1/deals`, `### GET /api/v1/deals/{id}`, `### PATCH /api/v1/deals/{id}` sections in the existing doc style (scope + blurb + curl example); add the two new scopes to the scopes table; remove the "deals/pipelines... not yet scheduled" line from the roadmap section (~line 377-383).

6. **`src/lib/api/v1/deals.test.ts`** (new) — unit-test `serializeDeal` with hand-built rows (including null `stage_id`/`assigned_to`), following `contacts.test.ts`'s convention (no live Supabase mock; DB-touching helpers get only their pre-DB validation branch tested via a `noopDb` cast).

## Part B — this app: real auth + real endpoint shapes + per-org wiring

Repo: this one. Files: `app/modules/lead_qualification/infrastructure/wacrm_client.py`, `application/lead_sync.py`, `wiring.py`.

1. **`wacrm_client.py`**:
   - `WacrmClient.__init__(self, base_url=None, api_key=None, timeout=10.0)` — when `api_key` is set, send `Authorization: Bearer {api_key}` on every request.
   - `_parse_snapshot(data, organization_id)` — real wacrm's deal payload has no `organization_id` field (that's implicit in which API key you called with); take `organization_id` as a parameter from the caller's own context instead of reading `data["organization_id"]`. Thread it through the four call sites (`get_lead`, `list_leads_updated_since`, `find_by_contact_reference`, `update_stage` already have it available).
   - `get_lead`: `GET /leads/{id}` → `GET /deals/{id}`.
   - `list_leads_updated_since`: `GET /leads?organization_id=&updated_since=` → `GET /deals?updated_since=` (drop `organization_id` — implicit via key).
   - `find_by_contact_reference`: `GET /leads?organization_id=&contact_reference=` → `GET /deals?contact_phone=`.
   - `update_stage`: `PATCH /leads/{id}/stage` body `{pipeline_stage, assigned_broker_id}` → `PATCH /deals/{id}` body `{stage_name: pipeline_stage, assigned_broker_id}`.

2. **`wiring.py`** — `sync_all_organizations_once` and `handle_profile_completed` currently build one global `WacrmClient()`/`LeadSyncAdapter(session)` per the mock's single shared URL. Change to per-organization:
   - Look up `OrganizationConfig` via the existing `OrganizationConfigRepository`/`OrganizationService.get_config(organization_id)` (`app/modules/organization/infrastructure/repository.py:51`, `application/service.py:35`) — this already deserializes `CrmConfig(base_url, api_key, tenant_ref)` from the `crm_config` JSON column, it's just never been read by `lead_qualification`.
   - If `config.crm` is set, construct `WacrmClient(base_url=config.crm.base_url, api_key=config.crm.api_key)` for that org (real wacrm). If `config.crm` is `None`, fall back to today's behavior — global `settings.wacrm_base_url`, no auth (keeps the mock-based dev flow working for orgs that haven't configured real wacrm yet; no breaking change).
   - Pass this per-org client into `LeadSyncAdapter(session, client=...)` (the adapter already accepts an injected `client`, per `test_lead_sync.py`'s `FakeWacrmClient` usage).

3. **`lead_sync.py`** — small robustness addition: in `_upsert_from_snapshot`, catch `ValueError` from `PipelineStage(snapshot.pipeline_stage)` per-lead (log a warning naming the org + crm_lead_id + offending stage string, skip that lead) instead of letting one mismatched stage name abort the whole org's poll pass. This is a new real-world failure mode once stage names come from a human-editable wacrm pipeline instead of the fixed mock — without it, one broker typo in a stage name takes down CDC sync for the entire organization.

## Part C — operational contract (no code, but must be documented)

wacrm's `pipeline_stages.name` is free-text, user-defined per pipeline. Our domain's `PipelineStage` (`app/modules/lead_qualification/domain/models.py`) is a **closed** enum: `New, Qualified, AppointmentSet, Visited, Negotiation, Won, Lost` (exact, case-sensitive). The pipeline used for CDC sync in wacrm **must** have its stages named exactly these 7 values, in this app's Architecture/onboarding docs (append a short note to `Documents/Oficial/Architecture.md` or wherever `CrmConfig`/onboarding is documented) — this is the join contract between an open-schema CRM and our closed domain enum, and it's an operator setup step, not something either codebase can enforce structurally beyond Part A's `resolveStageIdByName` giving a clear 400 on mismatch, and Part B's per-lead skip-and-log keeping a bad name from taking down the whole sync.

## Verification

1. **wacrm fork**: `cd wacrm && npm install && npm run typecheck && npm run build && npx vitest run src/lib/api/v1/deals.test.ts` — confirms the new route compiles and the serializer unit tests pass. Manual smoke test once a Supabase project + `npm run dev` is up: create a pipeline named with the 7 required stages, create a deal via the dashboard UI, then `curl` `GET /api/v1/deals`, `GET /api/v1/deals/{id}`, `PATCH /api/v1/deals/{id}` with a `deals:read`/`deals:write` key from Settings → API keys.
2. **This app**: `pytest tests/test_lead_sync.py -v` must still pass unchanged (it drives `LeadSyncAdapter` through `FakeWacrmClient`, not real HTTP, so Part B's client-shape changes shouldn't affect it — confirms the adapter-level contract is preserved). Then, once a real wacrm instance + org `CrmConfig` exists, an integration smoke test: set `OrganizationConfig.crm` for the demo org, run `sync_all_organizations_once()` directly (as done earlier this session against the mock) and confirm a deal created in wacrm's UI lands in the local `leads` table with the mapped fields.
3. Confirm the mock-based path (`docker-compose`, orgs with no `CrmConfig` set) still works exactly as before — no regression for local/offline dev.
