from datetime import date, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

PaymentStatus = Literal["PENDING", "SUCCESS", "FAILED", "CANCELLED", "REFUNDED"]
PaymentMethod = Literal["CASH", "BANK_TRANSFER", "UPI", "CARD", "CHEQUE", "ONLINE"]


class PaymentManualCreateRequest(BaseModel):
    """Admin records a payment that was already collected outside the app (cash, bank transfer, cheque, etc.)."""
    enrollment_id: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0, le=10000000)
    payment_date: Optional[date] = Field(None, description="Defaults to today if omitted")
    payment_method: PaymentMethod
    # Defaults to SUCCESS: a manual entry records something that already happened.
    # Explicitly overridable — e.g. a cheque awaiting clearance can be logged as PENDING.
    payment_status: Optional[PaymentStatus] = "SUCCESS"
    remarks: Optional[str] = Field(None, max_length=500)
    # ─── Phase 3 — advance contributions ───
    # Number of monthly installments this ONE transaction covers. 1 = ordinary
    # monthly contribution (unchanged behaviour). 3 / 6 = advance payment; the
    # amount must then equal scheme.monthly_amount * months_covered exactly.
    months_covered: Optional[Literal[1, 3, 6]] = 1
    # Optional caller-supplied idempotency key. If a payment with this reference
    # already exists for the tenant, the existing one is returned unchanged —
    # a retry or double-submit never creates a second contribution.
    idempotency_key: Optional[str] = Field(None, min_length=6, max_length=30)


class PaymentUpdateRequest(BaseModel):
    amount: Optional[float] = Field(None, gt=0, le=10000000)
    payment_date: Optional[date] = None
    payment_method: Optional[PaymentMethod] = None
    payment_status: Optional[PaymentStatus] = None
    remarks: Optional[str] = Field(None, max_length=500)


class PaymentResponse(BaseModel):
    """Admin-facing — includes tenant/enrollment IDs plus derived names for readability."""
    id: str
    tenant_id: str
    enrollment_id: str
    enrollment_number: str
    customer_name: str
    scheme_name: str
    passbook_entry_id: Optional[str] = None
    payment_reference: str
    amount: float
    payment_date: date
    payment_method: str
    payment_status: str
    months_covered: int = 1
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    gateway_name: Optional[str] = None
    gateway_transaction_id: Optional[str] = None
    remarks: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerPaymentResponse(BaseModel):
    """Customer-facing — lean, no tenant/internal IDs or gateway metadata."""
    id: str
    enrollment_id: str
    enrollment_number: str
    scheme_name: str
    payment_reference: str
    amount: float
    payment_date: date
    payment_method: str
    payment_status: str
    months_covered: int = 1
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    remarks: Optional[str] = None

    class Config:
        from_attributes = True
