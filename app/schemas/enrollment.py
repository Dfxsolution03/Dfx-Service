from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class EnrollmentCreateRequest(BaseModel):
    scheme_id: str = Field(..., min_length=1)
    # Optional selected tier. When given it must belong to the scheme and be
    # active; its (monthly_amount, duration_months) are snapshotted onto the
    # enrollment. Omit to enroll on the scheme's base terms (legacy behaviour).
    scheme_tier_id: Optional[str] = Field(None, min_length=1)


class EnrollmentResponse(BaseModel):
    """Admin-facing — includes tenant/customer/scheme IDs plus derived names for readability."""
    id: str
    tenant_id: str
    customer_id: str
    customer_name: str
    scheme_id: str
    scheme_name: str
    enrollment_number: str
    joined_date: date
    status: str
    maturity_date: date
    months_paid: int = 0
    next_due_date: Optional[date] = None
    remarks: Optional[str] = None
    # Effective (resolved) terms of THIS enrollment: the selected tier snapshot
    # when present, else the scheme's base terms. maturity_amount = monthly x duration.
    scheme_tier_id: Optional[str] = None
    monthly_amount: float = 0.0
    duration_months: int = 0
    maturity_amount: float = 0.0
    # Authoritative SUM of this enrollment's SUCCESSFUL contributions (ledger
    # truth, never monthly x months_paid). Lets Collections show the real paid
    # total that agrees with Payments/Passbook. 0.0 when unresolved by the caller.
    total_paid: float = 0.0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EnrollmentRemarksUpdate(BaseModel):
    remarks: Optional[str] = Field(None, max_length=500)


class CustomerEnrollmentResponse(BaseModel):
    """Customer-facing — lean, no tenant/customer IDs."""
    id: str
    scheme_id: str
    scheme_name: str
    enrollment_number: str
    joined_date: date
    status: str
    maturity_date: date
    months_paid: int = 0
    next_due_date: Optional[date] = None
    # Effective (resolved) terms of THIS enrollment — selected tier snapshot when
    # present, else the scheme's base terms. maturity_amount = monthly x duration.
    scheme_tier_id: Optional[str] = None
    monthly_amount: float = 0.0
    duration_months: int = 0
    maturity_amount: float = 0.0

    class Config:
        from_attributes = True


# =============================================================================
# Scheme closure and redemption
# =============================================================================

class SchemeRedemptionResponse(BaseModel):
    id: str
    enrollment_id: str
    customer_id: str
    sale_id: str
    invoice_number: str
    amount: float
    redeemed_at: datetime
    recorded_by: str
    recorded_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class EnrollmentBalanceResponse(BaseModel):
    """Authoritative scheme-credit position of one enrollment.

    Every figure is derived, never cached: total_paid comes from the SUCCESSFUL
    scheme payment ledger, total_redeemed from the redemption ledger, and
    available_balance is the difference. No bonus is included — the product has
    no numeric bonus rule.
    """
    enrollment_id: str
    enrollment_number: str
    customer_id: str
    customer_name: str
    scheme_name: str
    # Resolved terms of this enrollment (selected tier snapshot, else scheme base).
    scheme_tier_id: Optional[str] = None
    monthly_amount: float
    duration_months: int
    maturity_amount: float = 0.0
    # Coverage state, so a caller (e.g. the manual-payment picker) can show
    # months paid / remaining and the next due date without a second call.
    months_paid: int = 0
    next_due_date: Optional[date] = None
    successful_payment_count: int
    total_paid: float
    total_redeemed: float
    available_balance: float
    status: str
    joined_date: date
    maturity_date: date
    closed_at: Optional[datetime] = None
    closed_by: Optional[str] = None
    closed_by_name: Optional[str] = None
    closure_reason: Optional[str] = None
    can_contribute: bool
    can_redeem: bool
    redemptions: List[SchemeRedemptionResponse] = []


class EnrollmentCloseRequest(BaseModel):
    """Stop future contributions. The balance already paid in is preserved and
    stays redeemable — closing never refunds or forfeits it."""
    reason: str = Field(..., min_length=3, max_length=500)


class SchemeRedeemItem(BaseModel):
    """One enrollment's share of a multi-scheme settlement. The amount is per
    enrollment on purpose — a customer paying with three schemes must see, and
    the ledger must keep, exactly which scheme funded which rupee."""
    enrollment_id: str
    amount: float = Field(..., gt=0)


class MultiSchemeRedeemRequest(BaseModel):
    """Settle one invoice from several scheme balances in a SINGLE transaction.

    All-or-nothing: if any enrollment fails validation (ownership, status,
    balance) or the combined amount exceeds the invoice's outstanding, nothing
    is written at all. The frontend must never chain independent redemption
    calls and hope each one lands.
    """
    items: List[SchemeRedeemItem] = Field(..., min_length=1)
    # Phase 5 — the customer-app OTP authorising this sensitive redemption. The
    # code is verified and consumed server-side before any balance is spent.
    otp_code: str = Field(..., min_length=4, max_length=10)


class MultiSchemeRedeemResponse(BaseModel):
    """Post-settlement position: what the invoice now owes, and the refreshed
    balance of every enrollment that funded it."""
    sale_id: str
    invoice_number: str
    total_redeemed: float
    sale_final_amount: float
    sale_amount_paid: float
    sale_outstanding: float
    sale_payment_status: str
    balances: List["EnrollmentBalanceResponse"] = []


class SchemeRedeemRequest(BaseModel):
    """Apply scheme credit to an existing jewellery invoice."""
    sale_id: str
    amount: float = Field(..., gt=0, description="Never above the available balance or the sale's outstanding")


# Forward reference: MultiSchemeRedeemResponse cites EnrollmentBalanceResponse,
# which is declared above it in this module.
MultiSchemeRedeemResponse.model_rebuild()
