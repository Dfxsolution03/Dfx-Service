from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


class ProviderStatus(BaseModel):
    provider: str
    label: str
    configured: bool


class PlatformSettingsResponse(BaseModel):
    platform_name: str
    support_email: Optional[str] = None
    support_phone: Optional[str] = None
    default_currency: str
    default_timezone: str
    maintenance_mode: bool
    feature_flags: List[str] = Field(default_factory=list)
    updated_at: datetime
    # Computed, never persisted — see app/core/integration_registry.py.
    email_status: ProviderStatus
    whatsapp_status: ProviderStatus
    security_status: dict


class PlatformSettingsUpdateRequest(BaseModel):
    platform_name: Optional[str] = Field(None, min_length=2, max_length=100)
    support_email: Optional[EmailStr] = None
    support_phone: Optional[str] = Field(None, min_length=6, max_length=20)
    default_currency: Optional[str] = Field(None, min_length=3, max_length=10)
    default_timezone: Optional[str] = Field(None, min_length=2, max_length=50)
    maintenance_mode: Optional[bool] = None
    feature_flags: Optional[List[str]] = None


class PlatformSettingsStatusResponse(BaseModel):
    maintenance_mode: bool
    email_status: ProviderStatus
    whatsapp_status: ProviderStatus
    security_status: dict
