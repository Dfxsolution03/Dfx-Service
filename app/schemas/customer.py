import re
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    avatar_url: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Phone number must be a valid 10-digit Indian mobile number")
        return v


class CustomerProfileResponse(BaseModel):
    id: str
    tenant_id: Optional[str]
    tenant_name: str
    name: str
    email: Optional[str]
    phone: Optional[str]
    kyc_status: str
    member_since: Optional[str]
    avatar_url: Optional[str]

    class Config:
        from_attributes = True


class KYCSubmitRequest(BaseModel):
    doc_type: str = Field(..., description="Document type: PAN, Aadhaar, Passport")
    doc_number: str = Field(..., description="Document identification number")

    @field_validator("doc_type")
    @classmethod
    def validate_doc_type(cls, v: str) -> str:
        v_upper = v.upper().strip()
        if v_upper not in ["PAN", "AADHAAR", "PASSPORT"]:
            raise ValueError("Document type must be PAN, Aadhaar, or Passport")
        return v_upper

    @field_validator("doc_number")
    @classmethod
    def validate_doc_number(cls, v: str, info) -> str:
        v_clean = v.strip().upper()
        doc_type = info.data.get("doc_type")
        if doc_type == "PAN" and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$", v_clean):
            raise ValueError("Invalid PAN document number format (e.g. ABCDE1234F)")
        elif doc_type == "AADHAAR" and not re.match(r"^\d{12}$", v_clean):
            raise ValueError("Invalid Aadhaar number format (must be 12 digits)")
        return v_clean


class KYCResponse(BaseModel):
    id: str
    user_id: str
    doc_type: str
    doc_number: str
    status: str
    verified_at: Optional[str] = None
    rejection_reason: Optional[str] = None

    class Config:
        from_attributes = True


class KYCRejectRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=255)


class AdminKYCResponse(BaseModel):
    """Admin-facing — includes tenant/user IDs plus derived customer name for readability."""
    id: str
    tenant_id: str
    user_id: str
    customer_name: str
    customer_email: Optional[str]
    customer_phone: Optional[str]
    doc_type: str
    doc_number: str
    status: str
    verified_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class AddressCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(..., min_length=10, max_length=15)
    house: str = Field(..., min_length=1, max_length=255)
    street: str = Field(..., min_length=1, max_length=255)
    area: str = Field(..., min_length=1, max_length=255)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=100)
    pincode: str = Field(..., min_length=6, max_length=10)
    type: str = Field("Home", description="Address type: Home, Work, Other")
    is_default: bool = False

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Phone number must be a valid 10-digit Indian mobile number")
        return v

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: str) -> str:
        v_clean = v.strip()
        if not re.match(r"^\d{6}$", v_clean):
            raise ValueError("Pincode must be a 6-digit number")
        return v_clean


class AddressUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    house: Optional[str] = Field(None, min_length=1, max_length=255)
    street: Optional[str] = Field(None, min_length=1, max_length=255)
    area: Optional[str] = Field(None, min_length=1, max_length=255)
    city: Optional[str] = Field(None, min_length=1, max_length=100)
    state: Optional[str] = Field(None, min_length=1, max_length=100)
    pincode: Optional[str] = Field(None, min_length=6, max_length=10)
    type: Optional[str] = Field(None, description="Address type: Home, Work, Other")
    is_default: Optional[bool] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Phone number must be a valid 10-digit Indian mobile number")
        return v

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^\d{6}$", v.strip()):
            raise ValueError("Pincode must be a 6-digit number")
        return v


class AddressResponse(BaseModel):
    id: str
    user_id: str
    name: str
    phone: str
    house: str
    street: str
    area: str
    city: str
    state: str
    pincode: str
    country: str
    type: str
    is_default: bool

    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=72)


class KycDocumentSubmitRequest(BaseModel):
    document_type: str = Field(..., min_length=2, max_length=50)
    document_url: str = Field(..., min_length=1, max_length=1000)


class KycDocumentResponse(BaseModel):
    id: str
    document_type: str
    document_url: str
    verification_status: str
    created_at: datetime

    class Config:
        from_attributes = True


class BranchResponseItem(BaseModel):
    id: str
    name: str
    address: str
    phone: str
    latitude: float
    longitude: float
    is_active: bool

    class Config:
        from_attributes = True


# ─── Phase 6C / Module 33 — Admin Customer Management ───

class AdminCustomerListItem(BaseModel):
    """Admin-facing — lean list row, no address/enrollment detail (that's
    the detail endpoint's job)."""
    id: str
    name: str
    email: Optional[str]
    phone: Optional[str]
    kyc_status: str
    member_since: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


class AdminCustomerPaginationInfo(BaseModel):
    """Mirrors audit.py's PaginationInfo / customer_catalogue.py's
    ProductListPaginationInfo shape, per this codebase's established
    per-module-schema-file convention for list pagination."""
    page: int
    page_size: int
    total_items: int
    total_pages: int


class AdminCustomerDetailResponse(BaseModel):
    """Admin-facing detail — profile + KYC status + enrollment/investment
    summary, composed in the service layer (same composition pattern as
    DashboardService), not stored anywhere as a single row."""
    id: str
    name: str
    email: Optional[str]
    phone: Optional[str]
    kyc_status: str
    member_since: Optional[str]
    avatar_url: Optional[str]
    is_active: bool
    enrollment_count: int
    total_invested: float


# ─── Phase 6C / Module 33 — Vendor/Tenant Self-Service Profile ───

class TenantProfileResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    gst_number: Optional[str] = None
    brand_color: Optional[str] = None
    logo_url: Optional[str] = None

    class Config:
        from_attributes = True


class TenantProfileUpdateRequest(BaseModel):
    """All optional — partial update, same convention as AddressUpdateRequest.
    Deliberately has no `id`/`tenant_id`/`name`/`slug`/`status` field — a
    vendor Admin can only ever update their own tenant's contact/branding
    columns, never the tenant's identity/status, and tenant_id is always
    taken from current_user.tenant_id, never accepted from the request."""
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, min_length=10, max_length=15)
    gst_number: Optional[str] = Field(None, min_length=1, max_length=20)
    brand_color: Optional[str] = Field(None, min_length=1, max_length=20)
    logo_url: Optional[str] = Field(None, max_length=500)

    @field_validator("contact_phone")
    @classmethod
    def validate_contact_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Phone number must be a valid 10-digit Indian mobile number")
        return v
