"""Domain model for the Organization bounded context (QA-03: organization-ready).

Organization is the root of all logical isolation: every other aggregate in every
other bounded context carries organization_id. OrganizationConfig holds the
per-agency integration settings so onboarding is configuration-only, no redeploy.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from app.shared.domain.base import AggregateRoot, DomainEvent, ValueObject, new_id, utcnow


class OrgStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ONBOARDING = "onboarding"


@dataclass(frozen=True)
class OrganizationCreated(DomainEvent):
    name: str = ""


@dataclass(frozen=True)
class OrganizationConfigUpdated(DomainEvent):
    config_keys_changed: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChatwootConfig(ValueObject):
    inbox_id: str
    account_id: str
    api_access_token: str
    base_url: str


@dataclass(frozen=True)
class WhatsappBusinessConfig(ValueObject):
    phone_number_id: str
    business_account_id: str
    access_token: str


@dataclass(frozen=True)
class CrmConfig(ValueObject):
    """wacrm credentials for this organization (E7 CRM Synchronization)."""

    base_url: str
    api_key: str
    tenant_ref: str


@dataclass(frozen=True)
class GoogleWorkspaceConfig(ValueObject):
    service_account_json_ref: str
    calendar_id: str
    transcript_source_opt_in: bool = False


class Organization(AggregateRoot):
    def __init__(
        self, name: str, *, id: uuid.UUID | None = None, status: OrgStatus = OrgStatus.ONBOARDING
    ):
        super().__init__()
        self.id = id or new_id()
        self.name = name
        self.status = status
        self.created_at = utcnow()

    @classmethod
    def create(cls, name: str) -> Organization:
        org = cls(name=name)
        org.record_event(OrganizationCreated(organization_id=org.id, name=name))
        return org

    def activate(self) -> None:
        self.status = OrgStatus.ACTIVE

    def suspend(self) -> None:
        self.status = OrgStatus.SUSPENDED


@dataclass
class OrganizationConfig:
    """Entity holding the versioned integration configuration for one organization.

    Any field can be absent during onboarding (configuration is incremental);
    completeness is validated by the application service before activation.
    """

    organization_id: uuid.UUID
    chatwoot: ChatwootConfig | None = None
    whatsapp: WhatsappBusinessConfig | None = None
    crm: CrmConfig | None = None
    google_workspace: GoogleWorkspaceConfig | None = None
    updated_at: object = field(default_factory=utcnow)

    def is_complete_for_activation(self) -> bool:
        """Minimum viable config to leave `onboarding`: Chatwoot + WhatsApp + CRM."""
        return self.chatwoot is not None and self.whatsapp is not None and self.crm is not None
