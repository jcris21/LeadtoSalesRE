"""Application-wide settings, loaded from environment (.env). Per-organization
integration config (Chatwoot inbox, WhatsApp, Google Workspace, CRM credentials)
is NOT here — it lives in the OrganizationConfig aggregate in Postgres, per
ArchitecturalDrivers Sprint 0 ("per-organization configuration model")."""

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    # Supabase (System of Record for the AI domain: profiles, embeddings, KG,
    # Prompt Registry, tool config, decision traces).
    database_url: PostgresDsn
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None

    # Admin API auth
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 8

    # Chatwoot (SoR for conversations). Per-org inbox/API-key overrides live in
    # OrganizationConfig; these are only the platform-level defaults for local dev.
    chatwoot_base_url: str = "http://localhost:3000"
    chatwoot_platform_api_key: str | None = None

    # wacrm (SoR for leads/pipeline, CON-2). Local dev points at mocks/wacrm_mock;
    # per-org credentials move into OrganizationConfig when real wacrm lands.
    # (docker-compose exposes the mock on 8080; inside the compose network use
    # WACRM_BASE_URL=http://wacrm-mock:8080)
    wacrm_base_url: str = "http://localhost:8080"
    crm_sync_poll_interval_seconds: float = 30.0
    crm_staleness_threshold_seconds: int = 60  # QA-13 staleness bound
    # QA-14 gate, percent. 80.0 = 4 of the 5 BuyerProfile dimensions
    # (budget, locations, property_type, timeline) captured — US-215
    # recalibration for a recommendation-first flow; `must_haves` becomes a
    # post-Matching refinement dimension (Nivel 2, US-217).
    profile_completeness_threshold: float = 80.0

    # Event bus / outbox worker. G12 (docs/e2e-manual-chat-checklist.md): a
    # handler that fails on every delivery must not be retried every poll
    # interval forever — that burned the Gemini quota on 2026-07-23 (a schema
    # bug made every MessageReceived retry re-call the LLM, ~1 req/sec until
    # fixed). Exponential backoff between attempts, dead-letter after the
    # ceiling (row stays with `dead_lettered_at` + `last_error` set for manual
    # inspection instead of processing it forever).
    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 50
    outbox_max_attempts: int = 8
    outbox_retry_backoff_base_seconds: float = 2.0
    outbox_retry_backoff_max_seconds: float = 300.0

    # Conversation dormancy decay (per-stage/org-configurable thresholds arrive
    # with the Engagement module; this is the platform default).
    dormancy_threshold_hours: int = 72
    dormancy_scan_interval_seconds: float = 600.0

    # Recommendation pipeline (M4, §7.10). semantic_top_n is the Hybrid
    # Retrieval fan-in size before ranking; top_k is the Top-3 the Coordinator
    # receives; enrichment_timeout_ms is the Neighborhood Enrichment budget
    # inside the overall <15s QA-01 response target.
    recommendation_semantic_top_n: int = 10
    recommendation_top_k: int = 3
    recommendation_enrichment_timeout_ms: int = 3000

    # US-307: Google Maps API key for Neighborhood Enrichment (Places Nearby
    # Search). Same optional-credential convention as gemini_api_key/
    # groq_api_key: unset means the adapter skips the HTTP call entirely and
    # every property degrades to neighborhood=None, no network calls, no crash.
    google_maps_api_key: str | None = None

    # US-308: real embedding model (Gemini gemini-embedding-001, truncated to
    # 1536 dims for the vector(1536) column + HNSW index). When unset,
    # ingestion falls back to the deterministic HashEmbeddingModel so tests
    # and keyless dev environments make no network calls.
    gemini_api_key: str | None = None

    # G1 generative fallback: LLM-backed extraction when the deterministic
    # keyword extractors find no signal in a lead message. Reuses
    # `gemini_api_key` (one Google key for embeddings + LLM); with it unset
    # the fallback is disabled (keyword-only qualification), no network calls.
    generative_extractor_model: str = "gemini-2.5-flash"

    # G4 conversational brain: LLM-backed replies behind the provider-neutral
    # `ChatModelPort` (conversation_ownership/infrastructure/llm_brain.py).
    # Reuses the same platform key; with it unset the brain stays on
    # TemplateBrain (deterministic, offline). The value names a model of the
    # configured provider — swapping providers means a new ChatModelPort
    # adapter, not code changes upstream.
    conversation_llm_model: str = "gemini-2.5-flash"

    # G4 fallback provider: when set, Groq's OpenAI-compatible chat API backs
    # a second `ChatModelPort` the brain falls through to if Gemini raises
    # (quota, outage, transient 5xx) — tried before ever degrading to
    # TemplateBrain. Optional; with it unset, Gemini alone is the LLM path
    # (unchanged behavior).
    groq_api_key: str | None = None
    groq_conversation_llm_model: str = "llama-3.3-70b-versatile"

    otel_service_name: str = "lead-to-sales-system"
    otel_exporter_otlp_endpoint: str | None = None

    # LangSmith instrumentation: traces the conversational turn (LangGraph
    # chain) plus each Gemini call (LLM spans) for latency/quality debugging.
    # Off by default — same optional-credential convention as gemini_api_key:
    # with no key, no outbound calls, no behavior change. `langsmith_redact_pii`
    # gates whether prompts/replies (which carry lead names, phones, emails)
    # are scrubbed before leaving the process; keep this true unless the
    # LangSmith project is self-hosted and inside the same trust boundary.
    langsmith_tracing_enabled: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "lead-to-sales-system"
    langsmith_endpoint: str | None = None
    langsmith_redact_pii: bool = True

    # G13: durable LangGraph checkpointer. "postgres" survives process restarts
    # (AsyncPostgresSaver, own psycopg pool); "memory" is the pre-fix behavior,
    # useful as a rollback lever if the Postgres checkpointer misbehaves.
    conversation_checkpointer: Literal["memory", "postgres"] = "postgres"
    # Active checkpoint window, in turns (one turn = one user+assistant pair).
    # Turns evicted from the window are folded into TurnState.summary.
    conversation_history_window_turns: int = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()
