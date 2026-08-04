from datetime import date
from typing import List, Literal, Optional
from pydantic import BaseModel

ReportPeriod = Literal["today", "this_week", "this_month", "this_year"]


class DateRangeInfo(BaseModel):
    date_from: date
    date_to: date
    label: str


class PaymentTrendPoint(BaseModel):
    period_label: str
    total_amount: float
    payment_count: int


class PaymentSummaryResponse(BaseModel):
    """Reusable across the Reports page (revenue/collections/outstanding KPIs,
    monthly chart) and the Analytics page (avg installment size KPI)."""
    range: DateRangeInfo
    total_revenue: float
    total_revenue_growth_percent: Optional[float] = None
    outstanding_dues: float
    outstanding_dues_growth_percent: Optional[float] = None
    avg_installment_amount: float
    success_payment_count: int
    # Added Module 13 — already computed by the repository, just wasn't
    # surfaced until the Admin Dashboard's "Pending Installments" tile needed it.
    pending_payment_count: int
    monthly_trend: List[PaymentTrendPoint]


class TopCustomerItem(BaseModel):
    enrollment_id: str
    customer_id: str
    customer_name: str
    scheme_name: str
    enrollment_status: str
    total_invested: float
    # All-time accumulated balance for this enrollment (not date-range scoped,
    # unlike total_invested) — will read 0 for most rows until Payment-to-Passbook
    # wiring lands (documented gap, see SESSION_HANDOFF.md Module 10).
    gold_weight_grams: float


class TopCustomersResponse(BaseModel):
    range: DateRangeInfo
    customers: List[TopCustomerItem]


class EnrollmentTrendPoint(BaseModel):
    period_label: str
    new_enrollments: int


class EnrollmentSummaryResponse(BaseModel):
    range: DateRangeInfo
    active_count: int
    completed_count: int
    cancelled_count: int
    new_enrollments_in_range: int
    retention_rate_percent: Optional[float] = None
    # Always null: no leads/CRM capture exists anywhere in this backend, so a
    # lead-to-enrolment conversion rate cannot be honestly computed.
    conversion_funnel_percent: Optional[float] = None
    # Always null: no redemption/maturity-payout event is modeled anywhere yet.
    redemption_velocity_days: Optional[float] = None
    daily_trend: List[EnrollmentTrendPoint]


class GoldRateTrendPoint(BaseModel):
    date: date
    rate_24k: float


class GoldRateTrendResponse(BaseModel):
    range: DateRangeInfo
    trend: List[GoldRateTrendPoint]
    # Added Module 13 — day-over-day % change between the two most recent
    # points in `trend`. Null if the range has fewer than 2 rate entries.
    latest_change_percent: Optional[float] = None


class SchemeSummaryItem(BaseModel):
    scheme_id: str
    scheme_name: str
    is_active: bool
    active_enrollments: int
    total_collected: float


class SchemeSummaryResponse(BaseModel):
    range: DateRangeInfo
    schemes: List[SchemeSummaryItem]


class DashboardSummaryResponse(BaseModel):
    """Composed from the same repository methods as the other report responses.
    Built in Module 12 as a reusable foundation; consumed for the first time
    by the Admin Dashboard in Module 13."""
    range: DateRangeInfo
    total_revenue: float
    total_revenue_growth_percent: Optional[float] = None
    active_enrollments: int
    total_gold_accumulated_grams: float
    outstanding_dues: float
    # Added Module 13 — see ReportRepository.get_customer_count.
    total_customers: int
    total_customers_growth_percent: Optional[float] = None
