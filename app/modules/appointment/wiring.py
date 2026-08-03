"""Wiring for the Appointment bounded context (US-212).

No wiring module existed here before this change — `SchedulingService` was
fully implemented and tested (US-404) but nothing ever constructed a
`GoogleCalendarPort` for it outside test fixtures. `build_calendar_client`
mirrors `lead_qualification.wiring.build_wacrm_client`'s shape: per-organization
config lookup, a typed error on a present-but-incomplete config, and a
distinct signal (`CalendarNotConfiguredError`) when the org simply hasn't
onboarded Google Workspace yet — callers (see `scheduling_turn.py`) treat that
as an expected, gracefully-handled outcome rather than a crash.
"""

from __future__ import annotations

import uuid

import httpx

from app.modules.appointment.application.calendar_port import GoogleCalendarPort
from app.modules.appointment.infrastructure.google_calendar_client import GoogleCalendarClient
from app.modules.organization.infrastructure.repository import OrganizationConfigRepository

_http_client: httpx.AsyncClient | None = None


class CalendarNotConfiguredError(Exception):
    """Raised when an organization has no `google_workspace` configuration.
    Distinct from a malformed config (`ValueError`) so callers can tell
    "not onboarded yet" (expected, gracefully handled) apart from
    "misconfigured" (a real setup bug worth surfacing loudly)."""


def _get_http_client() -> httpx.AsyncClient:
    """Process-wide singleton, built lazily (never at import time — an event
    loop must already be running), same posture as
    `recommendation.wiring._get_enrichment_adapter`'s `httpx.AsyncClient`."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


async def build_calendar_client(session, organization_id: uuid.UUID) -> GoogleCalendarPort:
    """Per-organization `GoogleCalendarPort`. Raises `CalendarNotConfiguredError`
    when the organization has no `google_workspace` config yet; raises
    `ValueError` when the config exists but is incomplete (fail loudly on a
    real setup bug, same contract as `build_wacrm_client`)."""
    config = await OrganizationConfigRepository(session).get(organization_id)
    workspace = config.google_workspace if config is not None else None
    if workspace is None:
        raise CalendarNotConfiguredError(
            f"Organization {organization_id} has no google_workspace configuration"
        )
    if not workspace.service_account_json_ref or not workspace.calendar_id:
        raise ValueError(
            f"Organization {organization_id} has a GoogleWorkspaceConfig with a blank "
            "service_account_json_ref or calendar_id; fix or remove it"
        )
    return GoogleCalendarClient(workspace, http_client=_get_http_client())
