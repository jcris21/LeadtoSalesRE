Stack diferente: SQLAlchemy async + Alembic + LangGraph + Supabase/pgvector

mkdir -p docs

cat > docs/base-standards.md << 'EOF'

LeadtoSalesRE — Base Development Standards

Project context

Name: Lead to Sales System
Domain: AI-native omnichannel real estate lead qualification platform
Architecture: Modular Monolith with DDD bounded contexts (7 modules)
Sprint: 0 (Foundation) → 5 (Engagement) incremental delivery
Stack: FastAPI (Python 3.12 / uv) + SQLAlchemy async + PostgreSQL/Supabase
+ Alembic + pgvector + LangGraph + OpenTelemetry
Channels: WhatsApp (wacrm), Chatwoot omnichannel
Auth: JWT (python-jose + bcrypt), organization_id isolation, RLS policies
Observability: OpenTelemetry + AIDecisionTrace (already in Sprint 0)
Prompt Registry: versioned, DB-backed (already in Sprint 0)

Core principles


Spec before code — /opsx:propose before ANY bounded context implementation
DDD isolation — modules NEVER import from each other directly; use Event Bus
Alembic only — NEVER write DDL (CREATE/ALTER/DROP TABLE) outside alembic/versions/
SQLAlchemy async only — use async Session via get_db(); NEVER raw asyncpg queries in routes
LangGraph for agent logic — agent orchestration goes in app/<module>/agents/; never inline in routes
Outbox/Inbox pattern — domain events go to outbox_events table; never direct cross-module calls
TDD — write failing pytest test before implementing any handler, node, or service
English only — all code, docstrings, commits, ADRs in English
uv exclusively — uv add, uv run pytest, uv run alembic; never bare pip
90%+ coverage on app/ (pytest-asyncio, aiosqlite in-memory for tests)


Bounded contexts (7 modules) — Sprint roadmap


Organization (Sprint 0 — DONE): multi-tenant isolation, JWT admin auth
Conversation & Ownership (Sprint 1): Chatwoot webhook, lead assignment
Lead & Qualification (Sprint 2): LangGraph qualification graph, pgvector scoring
Recommendation (Sprint 3): property matching, vector similarity search
Appointment (Sprint 4): scheduling, calendar integration
Engagement (Sprint 5): follow-up sequences, WhatsApp via wacrm


Architecture rules


ALL cross-module communication via Outbox/Inbox (outbox_events + inbox_records tables)
RLS policies enabled: Supabase service_role bypasses RLS (documented in migrations)
pgvector for lead embeddings: use SQLAlchemy Column(Vector(1536)), not raw SQL
AIDecisionTrace: every LangGraph node decision MUST be traced via AIDecisionTrace model
Prompt Registry: LLM prompts NEVER hardcoded; always fetched from prompt_versions table
Organization isolation: every query MUST include organization_id filter — no exceptions


Package management


Python: uv add <pkg> | uv add --dev <pkg> | uv run <cmd>
Run server: uv run uvicorn app.main:app --reload
Migrations: uv run alembic upgrade head | uv run alembic revision --autogenerate -m "<msg>"
Tests: uv run pytest -v | uv run pytest --cov=app --cov-report=term-missing
Lint: uv run ruff check . && uv run ruff format .


LangGraph patterns


Agent graphs live in app/<module>/agents/<name>_graph.py
State schema: TypedDict with organization_id always present
Every node must call AIDecisionTrace.log() before returning
Use Prompt Registry to load system prompts: never f-string prompts in graph nodes
Graph edges must be documented in openspec/changes/<feature>/design.md before coding


Testing


Test files in tests/ matching test_*.py
Use aiosqlite in-memory (conftest.py already configured — DO NOT modify conftest)
Mock LangGraph: patch graph.invoke() with deterministic fixture responses
Mock Supabase: use aiosqlite in-memory (already configured)
Mock wacrm: use mocks/wacrm_mock (docker-compose already wires this)
Coverage: uv run pytest --cov=app --cov-fail-under=90


Security


JWT_SECRET, DATABASE_URL, SUPABASE_SERVICE_ROLE_KEY: environment variables ONLY
Never hardcode connection strings, tokens, or API keys
organization_id must be validated on EVERY authenticated endpoint
pgcrypto extension: use for any PII encryption (already enabled via migration)


References


Architecture: Documents/Oficial/Architecture.md
Agentic system: Documents/Oficial/Agentic_System.md
Architectural drivers: Documents/Oficial/ArchitecturalDrivers.md
API spec: docs/api-spec.yml (generate after Sprint 1)
Data model: docs/data-model.md (generate after Sprint 1)
Harness: docs/HARNESS.md
Feature intake: docs/FEATURE_INTAKE.md
EOF


echo "✓ docs/base-standards.md written"
