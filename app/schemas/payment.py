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
    remarks: Optional[str] = None

    class Config:
        from_attributes = True
