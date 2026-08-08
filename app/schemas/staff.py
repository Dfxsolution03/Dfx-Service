import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator


class StaffCreateRequest(BaseModel):
    """
    Phase 6C / Module 33 — deliberately has NO role field. The Staff role is
    hardcoded server-side in StaffService.create_staff — a Tenant Admin can
    never escalate a created account to Admin or SuperAdmin because there is
    no client-controllable input that could express that, not because of a
    runtime check that could be bypassed or forgotten.
    """
    name: str = Field(..., min_length=2, max_length=100, example="Priya Sharma")
    email: Optional[EmailStr] = Field(None, example="priya.staff@example.com")
    phone: Optional[str] = Field(None, min_length=10, max_length=15, example="9876543210")
    password: str = Field(..., min_length=6, max_length=100, example="Priya@123")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Phone number must be a valid 10-digit Indian mobile number")
        return v


class StaffStatusUpdateRequest(BaseModel):
    is_active: bool = Field(..., description="True to reactivate, False to deactivate")


class StaffResponse(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool
    member_since: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
