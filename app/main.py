"""FastAPI entrypoint: Modular Monolith, single deployment, multi-organization.

Sprint 0 wired Organization, Auth and Intelligence-AI-Admin (Prompt Registry).
Sprint 1 adds Conversation & Ownership (M2): Chatwoot webhook adapter,
Coordinator Agent consuming MessageReceived from the Event Bus, and the
dormancy-decay worker loop. Lead & Qualification, Recommendation, Appointment
and Engagement modules are added in their respective sprints.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import truststore
from fastapi import FastAPI

# Verify outbound TLS (OpenAI, Chatwoot, Maps) against the OS certificate
# store: corporate/AV TLS interception installs its root CA there but not in
# certifi's bundle, which makes every httpx call fail with
# CERTIFICATE_VERIFY_FAILED.
truststore.inject_into_ssl()

from app.core.config import get_settings
from app.core.organization_context import OrganizationContextMiddleware
from app.modules.auth.router import router as auth_router
from app.modules.conversation_memory.infrastructure import (
    db_models as conversation_memory_db_models,  # noqa: F401  (registers ORM on Base.metadata; no API router yet — AI-102)
)
from app.modules.conversation_ownership.api.webhook_router import router as webhooks_router
from app.modules.conversation_ownership.application.decay import decay_inactive_conversations
from app.modules.conversation_ownership.wiring import register_event_handlers
from app.modules.intelligence_ai_admin.api.router import router as prompts_router
from app.modules.lead_qualification.api.router import router as lead_qualification_router
from app.modules.lead_qualification.wiring import (
    crm_sync_loop,
)
from app.modules.lead_qualification.wiring import (
    register_event_handlers as register_lead_qualification_handlers,
)
from app.modules.organization.api.router import router as organizations_router
from app.modules.recommendation.wiring import (
    register_event_handlers as register_recommendation_handlers,
)
from app.shared.infrastructure.event_bus import event_bus
from app.shared.infrastructure.observability import setup_observability

logging.basicConfig(level=get_settings().log_level)

register_event_handlers(event_bus)
register_lead_qualification_handlers(event_bus)
register_recommendation_handlers(event_bus)


async def _dormancy_decay_loop() -> None:
    from app.core.database import session_scope

    settings = get_settings()
    while True:
        try:
            async with session_scope() as session:
                await decay_inactive_conversations(session)
        except Exception:  # noqa: BLE001 - the loop must survive transient DB errors
            logging.getLogger(__name__).exception("Dormancy decay pass failed")
        await asyncio.sleep(settings.dormancy_scan_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(event_bus.run_forever())
    decay_task = asyncio.create_task(_dormancy_decay_loop())
    crm_sync_task = asyncio.create_task(crm_sync_loop())
    try:
        yield
    finally:
        event_bus.stop()
        for task in (worker_task, decay_task, crm_sync_task):
            task.cancel()
        for task in (worker_task, decay_task, crm_sync_task):
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Lead to Sales System", version="0.1.0", lifespan=lifespan)
app.add_middleware(OrganizationContextMiddleware)
setup_observability(app)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(prompts_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(lead_qualification_router, prefix="/api/v1")


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
async def readyz() -> dict[str, str]:
    from sqlalchemy import text

    from app.core.database import get_engine

    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ready"}
