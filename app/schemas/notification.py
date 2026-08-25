from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

NotificationType = Literal["SCHEME", "PAYMENT", "SUPPORT", "KYC", "ANNOUNCEMENT", "GENERAL", "BIRTHDAY"]

DevicePlatform = Literal["ANDROID", "IOS", "WEB"]
PushProviderName = Literal["FCM", "APNS", "EXPO"]


class DeviceRegisterRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=512)
    platform: DevicePlatform
    provider: PushProviderName = "FCM"


class DeviceUnregisterRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=512)


class DeviceTokenResponse(BaseModel):
    id: str
    platform: str
    provider: str
    is_active: bool

    class Config:
        from_attributes = True


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
