from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class IntegrationResponse(BaseModel):
    """Never includes a raw credential — those are never persisted at all
    (see app/core/integration_registry.py)."""
    provider: str
    label: str
    category: str
    enabled: bool
    configured: bool
    status: str  # not_configured | configured_disabled | enabled | connection_failed
    last_tested_at: Optional[datetime] = None
    last_test_status: Optional[str] = None
    last_error: Optional[str] = None


class IntegrationEnableRequest(BaseModel):
    enabled: bool


class IntegrationTestResponse(BaseModel):
    provider: str
    status: str  # not_configured | success | failed
    message: str
    tested_at: datetime


class WebhookCreateRequest(BaseModel):
    url: str
    event_type: str
    is_active: bool = True
    max_retries: int = 3


class WebhookResponse(BaseModel):
    id: str
    url: str
    event_type: str
    is_active: bool
    max_retries: int
    last_delivery_at: Optional[datetime] = None
    last_delivery_status: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WebhookCreatedResponse(WebhookResponse):
    """Only returned once, at creation/rotation time — the only moment the
    raw signing secret is ever visible."""
    signing_secret: str
