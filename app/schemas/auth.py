from datetime import date
from typing import Optional, List, Any
from pydantic import BaseModel, EmailStr, Field, field_validator


def _reject_future_dob(v: Optional[date]) -> Optional[date]:
    """A date of birth cannot be in the future. Calendar validity and format
    (YYYY-MM-DD) are already enforced by the `date` type; this only adds the
    business rule. No min/max age rule is applied (business decision)."""
    if v is not None and v > date.today():
        raise ValueError("Date of birth cannot be in the future")
    return v


class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, example="Priya Sharma")
    email: Optional[EmailStr] = Field(None, example="priya@example.com")
    phone: Optional[str] = Field(None, min_length=10, max_length=15, example="9876543210")
    password: str = Field(..., min_length=6, max_length=100, example="Priya@123")
    tenant_id: str = Field(..., description="Selected Jewellery Store ID from public stores dropdown")
    # Required for a new customer (approved Phase-1 decision). Date only.
    date_of_birth: date = Field(..., description="Customer Date of Birth (YYYY-MM-DD)", example="1995-08-21")

    _dob_not_future = field_validator("date_of_birth")(_reject_future_dob)


class UserLoginRequest(BaseModel):
    username: str = Field(..., description="Email or mobile phone number", example="priya@example.com")
    password: str = Field(..., example="Priya@123")


class GoogleLoginRequest(BaseModel):
    """
    Deliberately carries no identity fields. Email, name and Google subject
    are read out of the cryptographically verified ID token server-side (see
    app/services/google_identity_service.py) — a client-supplied email would
    be an authentication bypass, since anyone could then claim any address.
    """

    id_token: str = Field(
        ...,
        min_length=1,
        description="Google OAuth ID token (JWT) obtained by the client from Google",
    )
    tenant_id: Optional[str] = Field(
        None,
        description=(
            "Selected Jewellery Store ID. Required only when this Google "
            "account has no account yet and one must be created; ignored for "
            "an existing user, whose store is whatever their own record says."
        ),
    )
    # Optional on the schema because this endpoint also serves existing-user
    # login (which needs no DOB). The service requires it only when creating a
    # brand-new Google customer. Date only; never read from the Google token.
    date_of_birth: Optional[date] = Field(None, example="1995-08-21")

    _dob_not_future = field_validator("date_of_birth")(_reject_future_dob)


class TokenResponseData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 1800  # seconds


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., description="Long-lived refresh token string")


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = Field(None, description="Current refresh token to revoke")
    all_devices: bool = Field(False, description="If True, revokes all refresh tokens for this user")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(..., example="priya@example.com")


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., description="Raw reset token from the emailed link")
    new_password: str = Field(..., min_length=6, max_length=100, example="NewPriya@123")


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(..., description="Raw verification token from the emailed link")


class UserResponse(BaseModel):
    id: str
    tenant_id: Optional[str]
    role: str
    name: str
    email: Optional[str]
    phone: Optional[str]
    kyc_status: str
    member_since: Optional[str]
    date_of_birth: Optional[date] = None
    is_active: bool
    # Staff-only module access grants (see app/core/constants.py's
    # ALL_STAFF_MODULES). Always empty for non-Staff roles — Admin/
    # SuperAdmin access is never gated by this.
    permissions: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class TenantPublicItem(BaseModel):
    id: str
    name: str
    slug: str

    class Config:
        from_attributes = True


class StandardSuccessResponse(BaseModel):
    success: bool = True
    message: str = "Operation completed successfully"
    data: Any = Field(default_factory=dict)
    meta: Any = Field(default_factory=dict)
