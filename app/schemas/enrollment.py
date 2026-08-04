from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class EnrollmentCreateRequest(BaseModel):
    scheme_id: str = Field(..., min_length=1)


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
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerEnrollmentResponse(BaseModel):
    """Customer-facing — lean, no tenant/customer IDs."""
    id: str
    scheme_id: str
    scheme_name: str
    enrollment_number: str
    joined_date: date
    status: str
    maturity_date: date

    class Config:
        from_attributes = True
