from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

NotificationChannel = Literal["IN_APP", "EMAIL", "WHATSAPP", "SMS", "PUSH"]
NotificationTargetType = Literal["ALL", "CUSTOMERS", "SCHEME"]
NotificationCampaignStatus = Literal["DRAFT", "SENT", "FAILED", "CANCELLED"]


class NotificationCampaignCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    body: str = Field(..., min_length=1, max_length=4000)
    channel: NotificationChannel = "IN_APP"
    target_type: NotificationTargetType = "ALL"
    # CUSTOMERS -> list of customer user ids. SCHEME -> single scheme id
    # (as the only element). ALL -> ignored.
    target_ids: List[str] = Field(default_factory=list)

    @field_validator("target_ids")
    @classmethod
    def validate_target_ids(cls, v: List[str], info) -> List[str]:
        target_type = info.data.get("target_type")
        if target_type == "CUSTOMERS" and not v:
            raise ValueError("target_ids must contain at least one customer id for target_type=CUSTOMERS")
        if target_type == "SCHEME" and len(v) != 1:
            raise ValueError("target_ids must contain exactly one scheme id for target_type=SCHEME")
        return v


class NotificationCampaignUpdateRequest(BaseModel):
    """Only allowed while the campaign is still DRAFT — enforced in the service."""
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    body: Optional[str] = Field(None, min_length=1, max_length=4000)
    channel: Optional[NotificationChannel] = None
    target_type: Optional[NotificationTargetType] = None
    target_ids: Optional[List[str]] = None


class NotificationCampaignResponse(BaseModel):
    id: str
    title: str
    body: str
    channel: str
    target_type: str
    target_ids: List[str] = Field(default_factory=list)
    status: str
    recipient_count: Optional[int] = None
    sent_at: Optional[datetime] = None
    error: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
