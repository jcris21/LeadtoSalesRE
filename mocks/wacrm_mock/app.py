"""Lightweight stand-in for wacrm (github.com/ArnasDon/wacrm) local development,
until real wacrm credentials/instance are available (per ArchitecturalDrivers
Section 2: wacrm is the System of Record for leads/pipeline). Implements just
enough of the surface CrmConfig/Lead Sync Adapter (Sprint 2, Architecture.md
§6.2) needs to develop and test against locally: read a lead, update its
pipeline stage, list activities. Not a reimplementation of wacrm — swap the
CRM_CONFIG base_url to a real wacrm instance when available and this mock is
no longer used.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="wacrm-mock", version="0.1.0")

PipelineStage = Literal[
    "New", "Qualified", "AppointmentSet", "Visited", "Negotiation", "Won", "Lost"
]


class Lead(BaseModel):
    id: str
    organization_id: str
    pipeline_stage: PipelineStage
    assigned_broker_id: str | None = None
    lead_score: float = 0.0
    updated_at: datetime
    #: External contact identifier (e.g. WhatsApp phone number) shared with
    #: Chatwoot, so the app can match a Conversation to this Lead without
    #: either system inventing an id the other doesn't know about.
    contact_reference: str | None = None


_LEADS: dict[str, Lead] = {
    "lead-demo-1": Lead(
        id="lead-demo-1",
        organization_id="00000000-0000-0000-0000-000000000001",
        pipeline_stage="New",
        assigned_broker_id=None,
        lead_score=0.0,
        updated_at=datetime.now(UTC),
        contact_reference="+5491100000000",
    )
}


class UpdateStageRequest(BaseModel):
    pipeline_stage: PipelineStage
    assigned_broker_id: str | None = None


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/leads", response_model=list[Lead])
async def list_leads(
    organization_id: str,
    updated_since: datetime | None = None,
    contact_reference: str | None = None,
) -> list[Lead]:
    """CDC read used by the Lead Sync Adapter (Sprint 2, §7.7): leads of one
    organization whose updated_at is strictly after the watermark. Also
    supports an exact `contact_reference` filter, used to resolve which Lead
    a Chatwoot Conversation belongs to (Sprint 3 identity matching)."""
    leads = [lead for lead in _LEADS.values() if lead.organization_id == organization_id]
    if updated_since is not None:
        if updated_since.tzinfo is None:
            updated_since = updated_since.replace(tzinfo=UTC)
        leads = [lead for lead in leads if lead.updated_at > updated_since]
    if contact_reference is not None:
        leads = [lead for lead in leads if lead.contact_reference == contact_reference]
    return sorted(leads, key=lambda lead: lead.updated_at)


@app.get("/leads/{lead_id}", response_model=Lead)
async def get_lead(lead_id: str) -> Lead:
    lead = _LEADS.get(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@app.patch("/leads/{lead_id}/stage", response_model=Lead)
async def update_stage(lead_id: str, request: UpdateStageRequest) -> Lead:
    lead = _LEADS.get(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    updated = lead.model_copy(
        update={
            "pipeline_stage": request.pipeline_stage,
            "assigned_broker_id": request.assigned_broker_id or lead.assigned_broker_id,
            "updated_at": datetime.now(UTC),
        }
    )
    _LEADS[lead_id] = updated
    return updated


@app.post("/leads", response_model=Lead, status_code=201)
async def create_lead(organization_id: str) -> Lead:
    lead_id = f"lead-{uuid.uuid4()}"
    lead = Lead(
        id=lead_id,
        organization_id=organization_id,
        pipeline_stage="New",
        updated_at=datetime.now(UTC),
    )
    _LEADS[lead_id] = lead
    return lead
