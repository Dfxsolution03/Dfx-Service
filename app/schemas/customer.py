import re
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator


def _reject_future_dob(v: Optional[date]) -> Optional[date]:
    """A date of birth cannot be in the future. Format/calendar validity is
    enforced by the `date` type; no min/max age rule (business decision)."""
    if v is not None and v > date.today():
        raise ValueError("Date of birth cannot be in the future")
    return v


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    avatar_url: Optional[str] = None
    # Existing customers may have no DOB; they can add/update it here. Optional.
    date_of_birth: Optional[date] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Phone number must be a valid 10-digit Indian mobile number")
        return v

    _dob_not_future = field_validator("date_of_birth")(_reject_future_dob)


class CustomerProfileResponse(BaseModel):
    id: str
    tenant_id: Optional[str]
    tenant_name: str
    name: str
    email: Optional[str]
    phone: Optional[str]
    kyc_status: str
    member_since: Optional[str]
    date_of_birth: Optional[date]
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


# ─── Phase 7 — Admin Branch Management ───

class BranchCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    address: str = Field(..., min_length=5, max_length=500)
    phone: str = Field(..., min_length=10, max_length=20)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class BranchUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    address: Optional[str] = Field(None, min_length=5, max_length=500)
    phone: Optional[str] = Field(None, min_length=10, max_length=20)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)


class BranchStatusUpdateRequest(BaseModel):
    is_active: bool


# ─── Phase 6C / Module 33 — Admin Customer Management ───

class AdminCustomerListItem(BaseModel):
    """Admin-facing — lean list row, no address/enrollment detail (that's
    the detail endpoint's job)."""
    id: str
    customer_code: Optional[str]
    name: str
    email: Optional[str]
    phone: Optional[str]
    kyc_status: str
    member_since: Optional[str]
    date_of_birth: Optional[date] = None
    is_active: bool
    # Derived at read time (WALK-IN | SCHEME CUSTOMER | HYBRID | NEW), never stored.
    customer_type: Optional[str] = None

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
    customer_code: Optional[str]
    name: str
    email: Optional[str]
    phone: Optional[str]
    kyc_status: str
    member_since: Optional[str]
    date_of_birth: Optional[date]
    avatar_url: Optional[str]
    is_active: bool
    enrollment_count: int
    total_invested: float


class AdminCustomerCreateRequest(BaseModel):
    """Admin-side manual customer creation (walk-in support). Phone AND email are
    both optional — a walk-in with neither can still be created and gets a
    Customer ID. The admin sets an initial password the customer can change
    later. An optional scheme_id enrolls the new customer immediately, returning
    the auto-generated Enrollment ID linked to this customer."""
    name: str = Field(..., min_length=2, max_length=100)
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=8, max_length=72)
    scheme_id: Optional[str] = Field(None, min_length=1)
    # Required for a new customer (approved Phase-1 decision). Date only.
    date_of_birth: date = Field(...)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Phone number must be a valid 10-digit Indian mobile number")
        return v

    _dob_not_future = field_validator("date_of_birth")(_reject_future_dob)


class AdminCustomerUpdateRequest(BaseModel):
    """Admin-side edit of an existing customer. All optional (partial update).
    Password, when supplied, is re-hashed; name/phone/email/is_active edited in
    place. tenant_id is never accepted — always the admin's own tenant."""
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8, max_length=72)
    is_active: Optional[bool] = None
    date_of_birth: Optional[date] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Phone number must be a valid 10-digit Indian mobile number")
        return v

    _dob_not_future = field_validator("date_of_birth")(_reject_future_dob)


class AdminCustomerCreateResponse(BaseModel):
    """Result of manual customer creation — the generated Customer ID
    (customer_code) and, when a scheme was chosen, the linked Enrollment ID."""
    id: str
    customer_code: Optional[str]
    name: str
    email: Optional[str]
    phone: Optional[str]
    is_active: bool
    enrollment_id: Optional[str] = None
    enrollment_number: Optional[str] = None


class AdminCustomerEnrollRequest(BaseModel):
    """Enrol an EXISTING customer into a scheme — no new customer is created, so
    a WALK-IN who joins a scheme becomes HYBRID under the same Customer ID."""
    scheme_id: str = Field(..., description="Scheme to enrol the existing customer into")


# ─── Phase 1 — Customer 360 (read-only composition) ───

# A customer is WALK-IN only once they have a real product purchase, SCHEME once
# they enrol (and have no purchase), HYBRID with both, and NEW when they have no
# business relationship yet (created/enquired but neither bought nor enrolled).
# All derived at read time from the customer's own sales/enrollments, never
# stored — one customer record changes type as their activity changes.
CUSTOMER_TYPE_WALK_IN = "WALK-IN"
CUSTOMER_TYPE_SCHEME = "SCHEME CUSTOMER"
CUSTOMER_TYPE_HYBRID = "HYBRID"
CUSTOMER_TYPE_NEW = "NEW"


class CustomerOverviewProfile(BaseModel):
    id: str
    customer_code: Optional[str]
    name: str
    email: Optional[str]
    phone: Optional[str]
    avatar_url: Optional[str]
    is_active: bool
    member_since: Optional[str]
    date_of_birth: Optional[date] = None
    created_at: Optional[datetime]
    # Derived at read time from the customer's own enrollments and sales —
    # deliberately NOT a stored customer_type column, so a walk-in who later
    # joins a scheme keeps the same customer record and simply reads as a
    # different type.
    customer_type: str


class CustomerOverviewKyc(BaseModel):
    status: str
    doc_type: Optional[str] = None
    record_status: Optional[str] = None
    verified_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    document_count: int = 0


class CustomerOverviewEnrollment(BaseModel):
    id: str
    enrollment_number: str
    scheme_name: str
    status: str
    joined_date: Optional[str] = None
    maturity_date: Optional[str] = None
    # Straight from SchemeBalanceService — this endpoint never recomputes a
    # scheme balance of its own.
    total_paid: float
    total_redeemed: float
    available_balance: float
    can_redeem: bool


class CustomerOverviewContribution(BaseModel):
    id: str
    enrollment_id: str
    entry_number: Optional[int] = None
    entry_date: Optional[datetime] = None
    amount: float
    description: Optional[str] = None


class CustomerOverviewRedemption(BaseModel):
    id: str
    enrollment_id: str
    enrollment_number: Optional[str] = None
    invoice_number: Optional[str] = None
    amount: float
    redeemed_at: Optional[datetime] = None


class CustomerOverviewPurchase(BaseModel):
    id: str
    invoice_number: str
    product_name: str
    product_code: Optional[str] = None
    sale_timestamp: Optional[datetime] = None
    final_amount: float
    amount_paid: float
    amount_refunded: float
    outstanding: float
    payment_status: str
    sale_status: str


class CustomerOverviewPayment(BaseModel):
    id: str
    sale_id: str
    invoice_number: Optional[str] = None
    amount: float
    payment_date: Optional[date] = None
    payment_method: Optional[str] = None
    source: str
    reference_no: Optional[str] = None


class CustomerOverviewReturn(BaseModel):
    sale_id: str
    invoice_number: Optional[str] = None
    reason: Optional[str] = None
    refund_amount: float
    written_off_amount: float
    scheme_restored: float
    inspection_outcome: Optional[str] = None
    returned_at: Optional[datetime] = None


class CustomerOverviewTotals(BaseModel):
    """Counts and sums composed from the rows already returned above — no new
    financial rule, no second ledger."""
    enrollment_count: int
    scheme_total_paid: float
    scheme_total_redeemed: float
    scheme_available_balance: float
    purchase_count: int
    purchase_total: float
    purchase_paid: float
    purchase_outstanding: float
    return_count: int
    refund_total: float


class CustomerOverviewResponse(BaseModel):
    profile: CustomerOverviewProfile
    kyc: CustomerOverviewKyc
    totals: CustomerOverviewTotals
    enrollments: List[CustomerOverviewEnrollment]
    contributions: List[CustomerOverviewContribution]
    redemptions: List[CustomerOverviewRedemption]
    purchases: List[CustomerOverviewPurchase]
    payments: List[CustomerOverviewPayment]
    returns: List[CustomerOverviewReturn]


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
