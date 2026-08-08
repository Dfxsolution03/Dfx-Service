from datetime import datetime
from typing import Literal
from pydantic import BaseModel

NotificationType = Literal["SCHEME", "PAYMENT", "SUPPORT", "KYC", "ANNOUNCEMENT", "GENERAL"]


class NotificationResponse(BaseModel):
    """Customer-facing — lean, no tenant_id/user_id."""
    id: str
    title: str
    message: str
    type: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int
