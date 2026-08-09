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
    # White-label / branding — platform-level, distinct from per-tenant
    # Tenant.brand_color/logo_url.
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    brand_color_primary: Optional[str] = None
    brand_color_secondary: Optional[str] = None
    login_tagline: Optional[str] = None
    email_from_name: Optional[str] = None
    custom_domain: Optional[str] = None
    custom_domain_status: str = "not_configured"


class PlatformSettingsUpdateRequest(BaseModel):
    platform_name: Optional[str] = Field(None, min_length=2, max_length=100)
    support_email: Optional[EmailStr] = None
    support_phone: Optional[str] = Field(None, min_length=6, max_length=20)
    default_currency: Optional[str] = Field(None, min_length=3, max_length=10)
    default_timezone: Optional[str] = Field(None, min_length=2, max_length=50)
    maintenance_mode: Optional[bool] = None
    feature_flags: Optional[List[str]] = None
    logo_url: Optional[str] = Field(None, max_length=1000)
    favicon_url: Optional[str] = Field(None, max_length=1000)
    brand_color_primary: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    brand_color_secondary: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    login_tagline: Optional[str] = Field(None, max_length=255)
    email_from_name: Optional[str] = Field(None, max_length=100)
    custom_domain: Optional[str] = Field(None, max_length=255)


class PlatformSettingsStatusResponse(BaseModel):
    maintenance_mode: bool
    email_status: ProviderStatus
    whatsapp_status: ProviderStatus
    security_status: dict
