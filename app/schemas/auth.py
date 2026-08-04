from typing import Optional, List, Any
from pydantic import BaseModel, EmailStr, Field


class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, example="Priya Sharma")
    email: Optional[EmailStr] = Field(None, example="priya@example.com")
    phone: Optional[str] = Field(None, min_length=10, max_length=15, example="9876543210")
    password: str = Field(..., min_length=6, max_length=100, example="Priya@123")
    tenant_id: str = Field(..., description="Selected Jewellery Store ID from public stores dropdown")


class UserLoginRequest(BaseModel):
    username: str = Field(..., description="Email or mobile phone number", example="priya@example.com")
    password: str = Field(..., example="Priya@123")


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
    is_active: bool

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
