from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class GoldRateCreateRequest(BaseModel):
    rate_24k: float = Field(..., gt=0, le=1000000, description="24 Karat gold rate in INR per gram")


class GoldRateUpdateRequest(BaseModel):
    rate_24k: float = Field(..., gt=0, le=1000000, description="24 Karat gold rate in INR per gram")


class GoldRateResponse(BaseModel):
    id: str
    tenant_id: str
    rate_24k: float
    effective_date: date
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerGoldRateResponse(BaseModel):
    rate_24k: float
    effective_date: date
    updated_at: datetime
    # None for a tenant's manually-entered daily rate (the pre-Module-31
    # path, unchanged). Set to the TenantPricingConfig mode string only when
    # the rate was resolved via Module 31 (LIVE_MARKET / LIVE_PLUS_MARKUP /
    # MANUAL_OVERRIDE) — additive field, safe for existing clients to ignore.
    source: Optional[str] = None
    # Always None on the pre-Module-31 manual path (that table has no silver
    # column). Populated only when Module 31 resolves the rate and the
    # tenant's config/market data includes a silver figure.
    silver_999: Optional[float] = None

    class Config:
        from_attributes = True
