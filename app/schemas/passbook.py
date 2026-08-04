from datetime import date
from typing import List, Optional
from pydantic import BaseModel


class PassbookEntryResponse(BaseModel):
    id: str
    entry_number: int
    entry_date: date
    description: str
    amount: float
    gold_rate: float
    gold_weight: float
    running_installment_count: int
    remarks: Optional[str] = None

    class Config:
        from_attributes = True


class PassbookEnrollmentInfo(BaseModel):
    id: str
    enrollment_number: str
    joined_date: date
    status: str
    maturity_date: date


class PassbookSchemeInfo(BaseModel):
    id: str
    name: str
    monthly_amount: float
    duration_months: int
    bonus_description: Optional[str] = None


class PassbookSummary(BaseModel):
    total_amount_paid: float
    total_gold_weight: float
    entry_count: int


class PassbookResponse(BaseModel):
    enrollment: PassbookEnrollmentInfo
    scheme: PassbookSchemeInfo
    entries: List[PassbookEntryResponse]
    summary: PassbookSummary
