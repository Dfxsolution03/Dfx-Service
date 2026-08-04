from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SchemeCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    monthly_amount: float = Field(..., gt=0, le=10000000, description="Minimum monthly installment in INR")
    duration_months: int = Field(..., gt=0, le=360, description="Scheme tenure in months")
    bonus_description: Optional[str] = Field(None, max_length=255, description="e.g. '8% bonus on maturity'")


class SchemeUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    monthly_amount: Optional[float] = Field(None, gt=0, le=10000000)
    duration_months: Optional[int] = Field(None, gt=0, le=360)
    bonus_description: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


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

    class Config:
        from_attributes = True


class CustomerSchemeResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    monthly_amount: float
    duration_months: int
    bonus_description: Optional[str] = None

    class Config:
        from_attributes = True
