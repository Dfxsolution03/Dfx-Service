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

    class Config:
        from_attributes = True
