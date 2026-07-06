# Lead to Sales System

AI-native omnichannel real estate lead qualification platform. See
`Documents/Oficial/ArchitecturalDrivers.md`, `Architecture.md` and
`Agentic_System.md` for the full architecture, epics and sprint roadmap this
codebase implements incrementally.

## Sprint 0 — Foundation (current)

Delivered: Modular Monolith (FastAPI), DDD module skeleton for all 7 bounded
contexts, Organization module with `organization_id` isolation, JWT admin auth,
internal Postgres-based Event Bus (Outbox/Inbox, idempotent), minimal versioned
Prompt Registry, OpenTelemetry + `AIDecisionTrace` observability, Alembic
migrations with RLS policies, docker-compose (Chatwoot + wacrm mock), CI.

Conversation & Ownership, Lead & Qualification, Recommendation, Appointment and
Engagement modules are stubs — they land in Sprints 1–5 respectively.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker + Docker Compose (for Chatwoot and the wacrm mock)
- A Supabase project (Settings → Database → Connection string, and the
  `service_role` key from Settings → API)

## Setup

```bash
cp .env.example .env
# edit .env: DATABASE_URL (Supabase pooled connection string), JWT_SECRET
uv sync
```

## Database migrations

```bash
uv run alembic upgrade head
```

This creates `organizations`, `organization_configs`, `admin_users`,
`prompt_templates`, `prompt_versions`, `ai_decision_traces`, `outbox_events`,
`inbox_records`, enables the `vector`/`pgcrypto` extensions, and applies RLS
policies (see the migration file for why RLS doesn't gate the backend's own
`service_role` connection — it's documented in code).

## Run locally

**Option A — just the API, against your real Supabase:**

```bash
uv run uvicorn app.main:app --reload
```

**Option B — full stack (API + Chatwoot + wacrm mock) via Docker:**

```bash
docker compose up --build
```

- API: http://localhost:8000/docs
- Chatwoot: http://localhost:3000 (first boot takes a minute — it runs
  `rails db:chatwoot_prepare` before serving)
- wacrm mock: http://localhost:8080/docs


## Smoke-test the happy path

```bash
# 1. Create an organization
curl -X POST localhost:8000/api/v1/organizations -H 'content-type: application/json' \
  -d '{"name": "Acme Realty"}'
# -> {"id": "...", "name": "Acme Realty", "status": "onboarding"}

# 2. Register an admin user for that org
curl -X POST localhost:8000/api/v1/auth/register -H 'content-type: application/json' \
  -d '{"organization_id": "<id from step 1>", "email": "admin@acme.com", "password": "s3cret-pw"}'

# 3. Log in
curl -X POST localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"email": "admin@acme.com", "password": "s3cret-pw"}'
# -> {"access_token": "...", "token_type": "bearer"}

# 4. Publish a prompt version (Bearer token from step 3)
curl -X POST localhost:8000/api/v1/prompts -H 'content-type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"agent_name": "coordinator", "version": "v1", "content": "You are the Coordinator agent..."}'

curl localhost:8000/api/v1/prompts/coordinator/active -H 'Authorization: Bearer <token>'
```

`GET /healthz` and `GET /readyz` (the latter checks DB connectivity) are also
available for a quick sanity check.

## Tests

```bash
uv run pytest -v      # 14 tests: auth, organization/config, prompt registry, event bus idempotency
uv run ruff check .   # lint
```

Tests run against an in-memory SQLite database (see `tests/conftest.py`) — no
Supabase connection needed to run the test suite.
