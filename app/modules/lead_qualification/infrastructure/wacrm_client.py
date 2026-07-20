"""HTTP client for wacrm (Anti-Corruption Layer, outer edge). Translates the
wacrm public-API wire format (`/api/v1/deals`) into `WacrmLeadSnapshot` and
nothing else — no domain logic here.

Two ways to run it (CON-2: wacrm stays SoR either way):

- **Real wacrm** — construct with the organization's `CrmConfig` values
  (`base_url`, `api_key`) plus its `organization_id`. Requests authenticate
  with `Authorization: Bearer <api_key>`; the key is account-scoped, so the
  deal payload carries no organization id — it is implicit in which key we
  called with, which is why the constructor takes it.
- **Mock fallback** — no args: global `settings.wacrm_base_url`, no auth.
  NOTE: `mocks/wacrm_mock` still speaks the OLD `/leads` shape and does not
  implement `/deals` — a known, accepted divergence until the mock is updated;
  orgs without a `CrmConfig` simply have no working CDC sync against the mock.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class WacrmLeadSnapshot:
    """One lead (wacrm 'deal') as wacrm reports it, normalized to our types."""

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


def _parse_snapshot(data: dict, organization_id: uuid.UUID | None = None) -> WacrmLeadSnapshot:
    """Normalize one deal payload. Real wacrm deals carry no organization id
    (it is implicit in the API key), so the caller supplies it from its own
    context; the legacy mock shape, which embeds `organization_id`, remains
    the fallback when the caller has none."""
    if organization_id is None:
        organization_id = uuid.UUID(str(data["organization_id"]))
    broker_raw = data.get("assigned_broker_id")
    broker_id: uuid.UUID | None = None
    if broker_raw:
        try:
            broker_id = uuid.UUID(str(broker_raw))
        except ValueError:
            broker_id = None  # wacrm broker ids may not be UUIDs; mapping lands in Sprint 4
    updated_at = datetime.fromisoformat(str(data["updated_at"]).replace("Z", "+00:00"))
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return WacrmLeadSnapshot(
        crm_lead_id=str(data["id"]),
        organization_id=organization_id,
        pipeline_stage=str(data["pipeline_stage"]),
        assigned_broker_id=broker_id,
        lead_score=float(data.get("lead_score") or 0.0),
        updated_at=updated_at,
        contact_reference=data.get("contact_reference"),
    )


def _unwrap(payload: object) -> object:
    """wacrm's public API wraps every response in `{"data": ...}`; the legacy
    mock returns the resource bare. Accept both."""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


#: Hard ceiling on pages followed per list call (50 items/page default →
#: 10k deals). A wacrm bug that never returns a null cursor, or an absurd
#: backlog, must fail loudly instead of hanging the org's poll forever.
MAX_LIST_PAGES = 200


class WacrmClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        organization_id: uuid.UUID | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = (base_url or get_settings().wacrm_base_url).rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._organization_id = organization_id
        self._timeout = timeout

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url, headers=self._headers, timeout=self._timeout
        )

    async def _list_deals(
        self, organization_id: uuid.UUID | None, params: dict[str, str]
    ) -> list[WacrmLeadSnapshot]:
        """GET /deals following keyset pagination until the last page."""
        snapshots: list[WacrmLeadSnapshot] = []
        cursor: str | None = None
        async with self._http() as client:
            for _ in range(MAX_LIST_PAGES):
                page_params = dict(params)
                if cursor:
                    page_params["cursor"] = cursor
                response = await client.get("/deals", params=page_params)
                response.raise_for_status()
                payload = response.json()
                items = _unwrap(payload)
                if not isinstance(items, list):
                    items = []
                snapshots.extend(_parse_snapshot(item, organization_id) for item in items)
                meta = payload.get("meta") if isinstance(payload, dict) else None
                cursor = meta.get("next_cursor") if isinstance(meta, dict) else None
                if not cursor:
                    return snapshots
        # Partial data must never advance a CDC watermark — abort the call.
        raise RuntimeError(
            f"wacrm /deals pagination did not terminate within {MAX_LIST_PAGES} pages"
        )

    async def get_lead(self, crm_lead_id: str) -> WacrmLeadSnapshot | None:
        async with self._http() as client:
            response = await client.get(f"/deals/{crm_lead_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return _parse_snapshot(_unwrap(response.json()), self._organization_id)

    async def list_leads_updated_since(
        self, organization_id: uuid.UUID, since: datetime
    ) -> list[WacrmLeadSnapshot]:
        """CDC read: deals whose updated_at is after the watermark (§7.7). The
        API key is account-scoped, so no organization filter goes on the wire —
        `organization_id` only stamps the snapshots."""
        return await self._list_deals(organization_id, {"updated_since": since.isoformat()})

    async def find_by_contact_reference(
        self, organization_id: uuid.UUID, contact_reference: str
    ) -> WacrmLeadSnapshot | None:
        """Resolves the Lead a Chatwoot Conversation belongs to (Sprint 3
        identity matching) by the one identifier both systems share."""
        results = await self._list_deals(organization_id, {"contact_phone": contact_reference})
        return results[0] if results else None

    async def create_lead(
        self, *, contact_reference: str, contact_name: str, dni: str | None = None
    ) -> WacrmLeadSnapshot:
        """G8: a lead born in the chat is created in wacrm (SoR) the moment
        the contact gives their name. The deal starts in stage 'New'; the
        phone is the shared `contact_reference` the LeadLinker matches on.
        `contact_dni` follows update_stage's convention: absent key, not null."""
        body: dict[str, object] = {
            "contact_phone": contact_reference,
            "contact_name": contact_name,
            "stage_name": "New",
        }
        if dni is not None:
            body["contact_dni"] = dni
        async with self._http() as client:
            response = await client.post("/deals", json=body)
            response.raise_for_status()
            return _parse_snapshot(_unwrap(response.json()), self._organization_id)

    async def update_stage(
        self, crm_lead_id: str, pipeline_stage: str, assigned_broker_id: uuid.UUID | None = None
    ) -> WacrmLeadSnapshot:
        """Write direction of the bidirectional sync (idempotent on wacrm's side).
        `stage_name` is resolved by wacrm against the deal's own pipeline —
        exact, case-sensitive; an unknown name is a 400 (the stage-naming
        contract's enforcement point)."""
        body: dict[str, object] = {"stage_name": pipeline_stage}
        if assigned_broker_id is not None:
            body["assigned_broker_id"] = str(assigned_broker_id)
        async with self._http() as client:
            response = await client.patch(f"/deals/{crm_lead_id}", json=body)
            response.raise_for_status()
            return _parse_snapshot(_unwrap(response.json()), self._organization_id)
