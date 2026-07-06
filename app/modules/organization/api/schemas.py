import uuid
from datetime import datetime

from pydantic import BaseModel


class CreateOrganizationRequest(BaseModel):
    name: str


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str


class ChatwootConfigDTO(BaseModel):
    inbox_id: str
    account_id: str
    api_access_token: str
    base_url: str


class WhatsappConfigDTO(BaseModel):
    phone_number_id: str
    business_account_id: str
    access_token: str


class CrmConfigDTO(BaseModel):
    base_url: str
    api_key: str
    tenant_ref: str


class GoogleWorkspaceConfigDTO(BaseModel):
    service_account_json_ref: str
    calendar_id: str
    transcript_source_opt_in: bool = False


class UpsertOrganizationConfigRequest(BaseModel):
    chatwoot: ChatwootConfigDTO | None = None
    whatsapp: WhatsappConfigDTO | None = None
    crm: CrmConfigDTO | None = None
    google_workspace: GoogleWorkspaceConfigDTO | None = None


class OrganizationConfigResponse(BaseModel):
    organization_id: uuid.UUID
    chatwoot: ChatwootConfigDTO | None
    whatsapp: WhatsappConfigDTO | None
    crm: CrmConfigDTO | None
    google_workspace: GoogleWorkspaceConfigDTO | None
    updated_at: datetime
    is_complete_for_activation: bool
