"""Application-wide settings, loaded from environment (.env). Per-organization
integration config (Chatwoot inbox, WhatsApp, Google Workspace, CRM credentials)
is NOT here — it lives in the OrganizationConfig aggregate in Postgres, per
ArchitecturalDrivers Sprint 0 ("per-organization configuration model")."""

from functools import lru_cache

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
    profile_completeness_threshold: float = 90.0  # QA-14 gate, percent

    # Event bus / outbox worker
    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 50

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

    otel_service_name: str = "lead-to-sales-system"
    otel_exporter_otlp_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
