from datetime import date
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

ReportPeriod = Literal["today", "this_week", "this_month", "this_year"]


# ─── Phase 6 — Business top customers + AI insights ───

class TopCustomerBySalesItem(BaseModel):
    customer_id: str
    customer_name: Optional[str] = None
    total_spent: float
    bill_count: int


class TopCustomersBySalesResponse(BaseModel):
    range: "DateRangeInfo"
    customers: List[TopCustomerBySalesItem]


class InsightItem(BaseModel):
    """One data-grounded insight. `evidence` carries the exact figures behind
    the statement so the frontend can present it and the admin can trust it —
    values are never fabricated (see InsightsResponse.data_available)."""
    id: str
    category: str
    title: str
    detail: str
    severity: Literal["info", "positive", "warning"] = "info"
    evidence: Dict[str, Any] = Field(default_factory=dict)


class InsightsResponse(BaseModel):
    range: "DateRangeInfo"
    module: Literal["business", "scheme"]
    # False when the range holds no underlying data — the response then carries
    # a single explanatory insight and NO invented metrics.
    data_available: bool
    insights: List[InsightItem] = Field(default_factory=list)
    note: Optional[str] = None


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
    # Sum of estimated maturity value of enrollments started in this bucket, so
    # the dashboard Collections chart can plot a Maturity metric. Estimate only.
    maturity_amount: float = 0.0


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


class SalesTrendPoint(BaseModel):
    period_label: str
    total_amount: float
    sale_count: int
    # Per-bucket profit (sum of realized gross margin) and gold weight sold, so
    # the dashboard Sales Trend chart can switch metric without more endpoints.
    profit: float = 0.0
    gold_weight_grams: float = 0.0


class SalesTrendResponse(BaseModel):
    """Business sales revenue time-series for the Admin Dashboard Sales Trend
    chart. Day buckets for short ranges, month buckets for long ones."""
    range: DateRangeInfo
    trend: List[SalesTrendPoint]


class CategorySalesItem(BaseModel):
    category: str
    total_sales: float
    bill_count: int
    # Share of total_sales in the range, 0..100, backend-computed so the
    # frontend never divides/ fabricates a percentage.
    percentage: float


class SalesByCategoryResponse(BaseModel):
    """Category breakdown for the Admin Dashboard Top Selling Categories donut."""
    range: DateRangeInfo
    total_sales: float
    categories: List[CategorySalesItem]


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


# ─── Phase 2A — AI Analyst ───

class AiAnalysisRequest(BaseModel):
    domain: Literal["BUSINESS", "SCHEME"]
    period: Optional[ReportPeriod] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class AiRecommendedAction(BaseModel):
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    title: str
    explanation: str
    # Supporting metric/value, when the underlying data provides one.
    metric: Optional[str] = None


class AiAnalysisResponse(BaseModel):
    domain: Literal["BUSINESS", "SCHEME"]
    range: "DateRangeInfo"
    # False when the AI provider is not configured, data is insufficient, or the
    # provider call failed — the frontend renders an "unavailable" panel and the
    # rest of Reports keeps working. `note` explains which.
    available: bool
    executive_summary: str = ""
    key_findings: List[str] = []
    opportunities: List[str] = []
    risks: List[str] = []
    recommended_actions: List[AiRecommendedAction] = []
    generated_at: Optional[str] = None
    model: Optional[str] = None
    note: Optional[str] = None


# ─── Birthday intelligence (Reports Analytics) ───

class BirthdayCustomer(BaseModel):
    customer_id: str
    customer_name: Optional[str] = None
    customer_code: Optional[str] = None
    # Calendar birthday as MM-DD (birth year is intentionally not exposed).
    birthday: str
    days_until_birthday: int


class BirthdaySummaryResponse(BaseModel):
    window_days: int
    total_with_dob: int
    today_count: int
    upcoming_count: int
    today: List[BirthdayCustomer]
    upcoming: List[BirthdayCustomer]


# Resolve the forward references to DateRangeInfo used by the Phase 6 models
# declared above it.
TopCustomersBySalesResponse.model_rebuild()
InsightsResponse.model_rebuild()
AiAnalysisResponse.model_rebuild()
