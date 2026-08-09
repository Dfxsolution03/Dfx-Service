import re
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.constants import ALL_STAFF_MODULES


def _validate_modules(v: List[str]) -> List[str]:
    unknown = set(v) - set(ALL_STAFF_MODULES)
    if unknown:
        raise ValueError(f"Unknown permission module(s): {', '.join(sorted(unknown))}")
    return v


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
    # Module access grants — see app/core/constants.py's ALL_STAFF_MODULES.
    # Empty list = no admin-panel module access (still a valid, real Staff
    # account, just with nothing granted yet).
    permissions: List[str] = Field(default_factory=list, example=["customers", "kyc"])

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Phone number must be a valid 10-digit Indian mobile number")
        return v

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: List[str]) -> List[str]:
        return _validate_modules(v)


class StaffStatusUpdateRequest(BaseModel):
    is_active: bool = Field(..., description="True to reactivate, False to deactivate")


class StaffPermissionsUpdateRequest(BaseModel):
    permissions: List[str] = Field(..., example=["customers", "catalogue"])

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: List[str]) -> List[str]:
        return _validate_modules(v)


class StaffResponse(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool
    member_since: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    created_at: datetime

    class Config:
        from_attributes = True
