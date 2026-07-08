"""HTTP client for wacrm (Anti-Corruption Layer, outer edge). Translates the
wacrm wire format into `WacrmLeadSnapshot` and nothing else — no domain logic
here. Local development points at mocks/wacrm_mock; swap `wacrm_base_url` to a
real instance and this client is unchanged (CON-2: wacrm stays SoR)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class WacrmLeadSnapshot:
    """One lead as wacrm reports it, normalized to our types."""

    crm_lead_id: str
    organization_id: uuid.UUID
    pipeline_stage: str
    assigned_broker_id: uuid.UUID | None
    lead_score: float
    updated_at: datetime
    #: External contact identifier (e.g. phone number) shared with Chatwoot;
    #: the sole shared key that lets a Conversation resolve to this Lead
    #: without either system inventing an identifier for the other.
    contact_reference: str | None = None


def _parse_snapshot(data: dict) -> WacrmLeadSnapshot:
    broker_raw = data.get("assigned_broker_id")
    broker_id: uuid.UUID | None = None
    if broker_raw:
        try:
            broker_id = uuid.UUID(str(broker_raw))
        except ValueError:
            broker_id = None  # wacrm broker ids may not be UUIDs; mapping lands in Sprint 4
    updated_at = datetime.fromisoformat(str(data["updated_at"]))
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return WacrmLeadSnapshot(
        crm_lead_id=str(data["id"]),
        organization_id=uuid.UUID(str(data["organization_id"])),
        pipeline_stage=str(data["pipeline_stage"]),
        assigned_broker_id=broker_id,
        lead_score=float(data.get("lead_score") or 0.0),
        updated_at=updated_at,
        contact_reference=data.get("contact_reference"),
    )


class WacrmClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self._base_url = (base_url or get_settings().wacrm_base_url).rstrip("/")
        self._timeout = timeout

    async def get_lead(self, crm_lead_id: str) -> WacrmLeadSnapshot | None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(f"/leads/{crm_lead_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return _parse_snapshot(response.json())

    async def list_leads_updated_since(
        self, organization_id: uuid.UUID, since: datetime
    ) -> list[WacrmLeadSnapshot]:
        """CDC read: leads whose updatedAt is strictly after the watermark (§7.7)."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(
                "/leads",
                params={
                    "organization_id": str(organization_id),
                    "updated_since": since.isoformat(),
                },
            )
            response.raise_for_status()
            return [_parse_snapshot(item) for item in response.json()]

    async def find_by_contact_reference(
        self, organization_id: uuid.UUID, contact_reference: str
    ) -> WacrmLeadSnapshot | None:
        """Resolves the Lead a Chatwoot Conversation belongs to (Sprint 3
        identity matching) by the one identifier both systems share."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(
                "/leads",
                params={
                    "organization_id": str(organization_id),
                    "contact_reference": contact_reference,
                },
            )
            response.raise_for_status()
            results = response.json()
            return _parse_snapshot(results[0]) if results else None

    async def update_stage(
        self, crm_lead_id: str, pipeline_stage: str, assigned_broker_id: uuid.UUID | None = None
    ) -> WacrmLeadSnapshot:
        """Write direction of the bidirectional sync (idempotent on wacrm's side)."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.patch(
                f"/leads/{crm_lead_id}/stage",
                json={
                    "pipeline_stage": pipeline_stage,
                    "assigned_broker_id": (
                        str(assigned_broker_id) if assigned_broker_id else None
                    ),
                },
            )
            response.raise_for_status()
            return _parse_snapshot(response.json())
