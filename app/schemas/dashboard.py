from datetime import date
from typing import List, Optional
from pydantic import BaseModel

from app.schemas.customer_catalogue import CustomerProductListItem


class DashboardProfileSummary(BaseModel):
    name: str
    avatar_url: Optional[str] = None
    kyc_status: str
    profile_completion_percent: int
    member_since: Optional[str] = None


class DashboardGoldRateSummary(BaseModel):
    rate_24k: float
    effective_date: date
    # Populated only once Module 31 (live market rate sync) resolves a rate
    # for this tenant — None on the pre-Module-31 manual-entry path.
    silver_999: Optional[float] = None


class DashboardSchemeSummary(BaseModel):
    active_enrollment_count: int
    total_invested: float
    total_gold_accumulated_grams: float


class DashboardPassbookEntryItem(BaseModel):
    id: str
    entry_date: date
    description: str
    amount: float
    gold_rate: float
    gold_weight: float

    class Config:
        from_attributes = True


class DashboardPassbookSummary(BaseModel):
    recent_entries: List[DashboardPassbookEntryItem]


class DashboardPaymentItem(BaseModel):
    id: str
    scheme_name: str
    amount: float
    payment_date: date
    payment_method: str
    payment_status: str

    class Config:
        from_attributes = True


class DashboardPaymentSummary(BaseModel):
    recent_payments: List[DashboardPaymentItem]
    pending_count: int


class DashboardSupportSummary(BaseModel):
    open_ticket_count: int


class DashboardNotificationSummary(BaseModel):
    unread_count: int


class DashboardResponse(BaseModel):
    profile: DashboardProfileSummary
    gold_rate: Optional[DashboardGoldRateSummary] = None
    schemes: DashboardSchemeSummary
    passbook: DashboardPassbookSummary
    payments: DashboardPaymentSummary
    wishlist_count: int
    support: DashboardSupportSummary
    notifications: DashboardNotificationSummary
    featured_products: List[CustomerProductListItem]
