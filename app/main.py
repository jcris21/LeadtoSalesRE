"""FastAPI entrypoint: Modular Monolith, single deployment, multi-organization.

Sprint 0 wires only the Organization, Auth and Intelligence-AI-Admin (Prompt
Registry) modules. Conversation & Ownership, Lead & Qualification,
Recommendation, Appointment and Engagement modules are added in their
respective sprints (see each module's __init__.py docstring).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.modules.auth.router import router as auth_router
from app.modules.intelligence_ai_admin.api.router import router as prompts_router
from app.modules.organization.api.router import router as organizations_router
from app.shared.infrastructure.event_bus import event_bus
from app.shared.infrastructure.observability import setup_observability

logging.basicConfig(level=get_settings().log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(event_bus.run_forever())
    try:
        yield
    finally:
        event_bus.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Lead to Sales System", version="0.1.0", lifespan=lifespan)
setup_observability(app)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(prompts_router, prefix="/api/v1")


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
