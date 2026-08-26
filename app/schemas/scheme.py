from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Scheme Tier Plans ───

class SchemeTierInput(BaseModel):
    """One tier supplied on scheme create/update. Maturity is derived, never
    supplied — it is always monthly_amount x duration_months."""
    monthly_amount: float = Field(..., gt=0, le=10000000)
    duration_months: int = Field(..., gt=0, le=360)
    is_active: bool = True


class SchemeTierResponse(BaseModel):
    id: str
    scheme_id: str
    monthly_amount: float
    duration_months: int
    is_active: bool
    # Derived: monthly_amount x duration_months. No bonus/interest/appreciation.
    maturity_amount: float = 0.0

    class Config:
        from_attributes = True

    @model_validator(mode="after")
    def _compute_maturity(self):
        self.maturity_amount = round(self.monthly_amount * self.duration_months, 2)
        return self


def _reject_duplicate_tiers(v):
    """A scheme may not list the same (monthly_amount, duration_months) twice —
    that is one tier, not two. Enforced here at the API layer and again by a DB
    unique constraint (uq_scheme_tiers_scheme_amount_duration)."""
    if v is None:
        return v
    seen = set()
    for t in v:
        key = (t.monthly_amount, t.duration_months)
        if key in seen:
            raise ValueError(
                f"Duplicate tier: {t.monthly_amount} x {t.duration_months} months is listed more than once"
            )
        seen.add(key)
    return v


class SchemeCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    monthly_amount: float = Field(..., gt=0, le=10000000, description="Minimum monthly installment in INR")
    duration_months: int = Field(..., gt=0, le=360, description="Scheme tenure in months")
    bonus_description: Optional[str] = Field(None, max_length=255, description="e.g. '8% bonus on maturity'")
    # Optional selectable tiers. Omit for a single-plan scheme (legacy behaviour).
    tiers: Optional[List[SchemeTierInput]] = None

    _validate_tiers = field_validator("tiers")(_reject_duplicate_tiers)


class SchemeUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    monthly_amount: Optional[float] = Field(None, gt=0, le=10000000)
    duration_months: Optional[int] = Field(None, gt=0, le=360)
    bonus_description: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None
    # When provided, the tier set is reconciled: matching (amount, duration)
    # tiers keep their identity, new ones are added, and any existing tier not in
    # the list is DEACTIVATED (never deleted). Omit to leave tiers untouched.
    tiers: Optional[List[SchemeTierInput]] = None

    _validate_tiers = field_validator("tiers")(_reject_duplicate_tiers)


class SchemeResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str] = None
    monthly_amount: float
    duration_months: int
    bonus_description: Optional[str] = None
    is_active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    # Full tier grid (active + inactive) for the admin.
    tiers: List[SchemeTierResponse] = []

    class Config:
        from_attributes = True


class CustomerSchemeResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    monthly_amount: float
    duration_months: int
    bonus_description: Optional[str] = None
    # Only ACTIVE tiers are offered to the customer to select from.
    tiers: List[SchemeTierResponse] = []

    class Config:
        from_attributes = True


# ─── Phase 2 — Scheme Request lifecycle ───

class SchemeRequestCreate(BaseModel):
    scheme_id: str


class SchemeRequestReject(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class SchemeRequestResponse(BaseModel):
    id: str
    customer_id: str
    customer_name: Optional[str] = None
    customer_code: Optional[str] = None
    scheme_id: str
    scheme_name: Optional[str] = None
    status: str
    kyc_status_at_request: Optional[str] = None
    kyc_status_current: Optional[str] = None
    enrollment_id: Optional[str] = None
    enrollment_number: Optional[str] = None
    rejection_reason: Optional[str] = None
    requested_by: Optional[str] = None
    approved_by: Optional[str] = None
    rejected_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
