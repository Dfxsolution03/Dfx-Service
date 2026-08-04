import re
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
