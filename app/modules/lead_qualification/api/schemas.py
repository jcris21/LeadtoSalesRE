"""Request/response DTOs for the support/QA progressive-profiling endpoints
(US-202-US-205). These mirror `ProfilePatch`'s shape 1:1, one DTO per
dimension - see design.md "Support endpoints are REST, one per dimension"."""

from pydantic import BaseModel, Field

from app.modules.lead_qualification.domain.models import PropertyType, Timeline


class BudgetCaptureRequest(BaseModel):
    minimum: float
    maximum: float


class LocationsCaptureRequest(BaseModel):
    locations: list[str] = Field(min_length=1)


class PropertyTypeCaptureRequest(BaseModel):
    property_type: PropertyType


class TimelineCaptureRequest(BaseModel):
    timeline: Timeline


class MustHavesCaptureRequest(BaseModel):
    must_haves: list[str] = Field(min_length=1)


class ProfileCaptureResponse(BaseModel):
    completeness: float
    captured_dimensions: list[str]
