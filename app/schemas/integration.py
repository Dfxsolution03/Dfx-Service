from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ConfigFieldSchema(BaseModel):
    """Describes one configurable field for a provider's Configure form —
    the frontend renders forms from this, no per-provider hardcoding."""
    key: str
    label: str
    secret: bool
    required: bool
    type: str


class IntegrationResponse(BaseModel):
    """Never includes a raw credential — those are encrypted at rest and
    only ever decrypted server-side for a real connection test (see
    app/core/crypto.py / IntegrationService). `masked_config` shows only
    non-secret values in full and secret values as a trailing-4-char mask."""
    provider: str
    label: str
    category: str
    enabled: bool
    configured: bool
    status: str  # not_configured | configured_disabled | enabled | connection_failed
    last_tested_at: Optional[datetime] = None
    last_test_status: Optional[str] = None
    last_error: Optional[str] = None
    fields: List[ConfigFieldSchema] = []
    masked_config: Dict[str, Any] = {}


class IntegrationConfigRequest(BaseModel):
    """Raw field values from the Configure form — validated against the
    provider's ConfigField list server-side, encrypted immediately, never
    logged (see IntegrationService.save_config)."""
    values: Dict[str, Any]


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
