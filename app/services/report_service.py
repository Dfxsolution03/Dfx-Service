from datetime import date, datetime, timezone, timedelta
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.enrollment import STATUS_ACTIVE, STATUS_COMPLETED, STATUS_CANCELLED
from app.repositories.report_repository import ReportRepository
from app.exceptions.base import ForbiddenException, ValidationException
from app.schemas.report import (
    DateRangeInfo,
    PaymentSummaryResponse,
    PaymentTrendPoint,
    TopCustomerItem,
    TopCustomersResponse,
    EnrollmentSummaryResponse,
    EnrollmentTrendPoint,
    GoldRateTrendResponse,
    GoldRateTrendPoint,
    SchemeSummaryResponse,
    SchemeSummaryItem,
    DashboardSummaryResponse,
    SalesTrendPoint,
    SalesTrendResponse,
    CategorySalesItem,
    SalesByCategoryResponse,
    TopCustomerBySalesItem,
    TopCustomersBySalesResponse,
    InsightItem,
    InsightsResponse,
)
from app.schemas.export import ExportFileResponse, ExportFormat
from app.services.export_service import ExportService, ExportColumn

# Same fixed-offset convention as goldrate_service.py — India-only business,
# IST has no DST so no tzdata package is needed.
IST = timezone(timedelta(hours=5, minutes=30))


def _today_ist() -> date:
    return datetime.now(IST).date()


def _resolve_range(
    period: Optional[str], date_from: Optional[date], date_to: Optional[date]
) -> Tuple[date, date, str]:
    """Resolve the effective [date_from, date_to] window and a display label.
    Explicit date_from/date_to (both required together) take precedence over
    `period`. `period` values are already validated by the endpoint's Literal
    query-param type, so only the custom-range combination needs checking here."""
    if date_from or date_to:
        if not date_from or not date_to:
            raise ValidationException("Both date_from and date_to are required when using a custom range")
        if date_from > date_to:
            raise ValidationException("date_from must be on or before date_to")
        return date_from, date_to, "Custom Range"

    today = _today_ist()
    p = period or "this_month"
    if p == "today":
        return today, today, "Today"
    if p == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, today, "This Week"
    if p == "this_year":
        return today.replace(month=1, day=1), today, "This Year"
    # this_month (default)
    return today.replace(day=1), today, "This Month"


def _previous_range(date_from: date, date_to: date) -> Tuple[date, date]:
    """Equivalent-length window immediately preceding [date_from, date_to] — used
    to compute growth_percent fields. All calculations happen here, backend-side."""
    span_days = (date_to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=span_days - 1)
    return prev_from, prev_to


def _growth_percent(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


def _label_bucket(bucket, group_by_month: bool) -> str:
    """`bucket` is a plain `date` for day-granularity rows, or a `datetime`
    (Postgres date_trunc always returns a timestamp) for month-granularity rows."""
    d = bucket.date() if isinstance(bucket, datetime) else bucket
    return d.strftime("%b %Y") if group_by_month else d.strftime("%d %b")


def _end_of_day_ist(d: date) -> datetime:
    """IST end-of-day instant for a calendar date — used as an 'as of' cutoff
    for point-in-time counts (e.g. total customers as of the end of a period)."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=IST)


BIRTHDAY_WINDOW_DAYS = 30  # Phase 10 — approved upcoming-birthday window.


def _next_birthday_days(dob: date, today: date, window: int = BIRTHDAY_WINDOW_DAYS) -> Optional[int]:
    """Days until the customer's NEXT birthday, matched on month+day only
    (birth year ignored). Returns None when the next birthday is outside the
    window. A Feb-29 birthday falls back to Feb-28 in non-leap years."""
    def _bday(year: int) -> date:
        try:
            return date(year, dob.month, dob.day)
        except ValueError:  # Feb 29 in a non-leap year
            return date(year, dob.month, 28)

    upcoming = _bday(today.year)
    if upcoming < today:
        upcoming = _bday(today.year + 1)
    days = (upcoming - today).days
    return days if 0 <= days <= window else None


class ReportService:
    @staticmethod
    def _require_tenant(current_user: User) -> str:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        return current_user.tenant_id

    # ─── Payments ───

    @staticmethod
    async def get_payment_summary(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> PaymentSummaryResponse:
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)
        prev_from, prev_to = _previous_range(d_from, d_to)

        current = await ReportRepository.get_payment_totals(db, tenant_id, d_from, d_to)
        previous = await ReportRepository.get_payment_totals(db, tenant_id, prev_from, prev_to)

        group_by_month = (d_to - d_from).days > 31
        trend_rows = await ReportRepository.get_payment_trend(db, tenant_id, d_from, d_to, group_by_month)

        avg_amount = (current["success_amount"] / current["success_count"]) if current["success_count"] else 0.0

        return PaymentSummaryResponse(
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            total_revenue=current["success_amount"],
            total_revenue_growth_percent=_growth_percent(current["success_amount"], previous["success_amount"]),
            outstanding_dues=current["pending_amount"],
            outstanding_dues_growth_percent=_growth_percent(current["pending_amount"], previous["pending_amount"]),
            avg_installment_amount=round(avg_amount, 2),
            success_payment_count=current["success_count"],
            pending_payment_count=current["pending_count"],
            monthly_trend=[
                PaymentTrendPoint(
                    period_label=_label_bucket(row["bucket"], group_by_month),
                    total_amount=row["total_amount"],
                    payment_count=row["payment_count"],
                )
                for row in trend_rows
            ],
        )

    # ─── Dashboard — Business sales aggregations (Module 13 Dashboard) ───

    @staticmethod
    async def get_sales_trend(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> SalesTrendResponse:
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)
        group_by_month = (d_to - d_from).days > 31
        rows = await ReportRepository.get_sales_trend(db, tenant_id, d_from, d_to, group_by_month)
        return SalesTrendResponse(
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            trend=[
                SalesTrendPoint(
                    period_label=_label_bucket(row["bucket"], group_by_month),
                    total_amount=round(row["total_amount"], 2),
                    sale_count=row["sale_count"],
                    profit=round(row.get("profit", 0.0), 2),
                    gold_weight_grams=round(row.get("gold_weight_grams", 0.0), 3),
                )
                for row in rows
            ],
        )

    @staticmethod
    async def get_sales_by_category(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> SalesByCategoryResponse:
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)
        rows = await ReportRepository.get_sales_by_category(db, tenant_id, d_from, d_to)
        total = sum(r["total_sales"] for r in rows)
        return SalesByCategoryResponse(
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            total_sales=round(total, 2),
            categories=[
                CategorySalesItem(
                    category=r["category"],
                    total_sales=round(r["total_sales"], 2),
                    bill_count=r["bill_count"],
                    percentage=round((r["total_sales"] / total) * 100, 1) if total else 0.0,
                )
                for r in rows
            ],
        )

    @staticmethod
    async def get_top_customers(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
        limit: int,
    ) -> TopCustomersResponse:
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)

        rows = await ReportRepository.get_top_enrollments_by_investment(db, tenant_id, d_from, d_to, limit)

        return TopCustomersResponse(
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            customers=[TopCustomerItem(**row) for row in rows],
        )

    # ─── Phase 6 — Business top customers + AI insights ───

    @staticmethod
    async def get_top_customers_by_sales(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
        limit: int,
    ) -> TopCustomersBySalesResponse:
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)
        rows = await ReportRepository.get_top_customers_by_sales(db, tenant_id, d_from, d_to, limit)
        return TopCustomersBySalesResponse(
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            customers=[TopCustomerBySalesItem(**row) for row in rows],
        )

    @staticmethod
    async def _birthday_insight(db, tenant_id, customer_rows, today, module):
        """Phase 10 — build a birthday/complimentary insight from the customers
        ALREADY ranked by the caller (business top customers / scheme top
        customers). Looks up their real DOBs (NULL excluded) and keeps only
        birthdays within the 30-day window. Returns None — never a fabricated
        insight — when no eligible birthday exists."""
        ids = list({r["customer_id"] for r in customer_rows if r.get("customer_id")})
        if not ids:
            return None
        dobs = await ReportRepository.get_dobs_for_customers(db, tenant_id, ids)
        upcoming = []
        for row in dobs:
            days = _next_birthday_days(row["date_of_birth"], today)
            if days is not None:
                upcoming.append({
                    "customer_id": row["customer_id"],
                    "customer_name": row["customer_name"],
                    "birthday": row["date_of_birth"].strftime("%m-%d"),
                    "days_until_birthday": days,
                })
        if not upcoming:
            return None
        upcoming.sort(key=lambda x: x["days_until_birthday"])
        names = ", ".join((u["customer_name"] or "A customer") for u in upcoming[:5])
        return InsightItem(
            id="birthday_complimentary", category="birthday", severity="info",
            title=f"Top {module} customer birthdays in the next {BIRTHDAY_WINDOW_DAYS} days",
            detail=f"{len(upcoming)} top {module} customer(s) have a birthday within "
                   f"{BIRTHDAY_WINDOW_DAYS} days ({names}) — a chance to send a complimentary gift.",
            evidence={"window_days": BIRTHDAY_WINDOW_DAYS, "customers": upcoming},
        )

    @staticmethod
    async def get_business_insights(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> InsightsResponse:
        """Data-grounded business insights. Every figure comes from a real
        aggregate over COMPLETED sales in the range; when there are none, the
        response says so and invents nothing."""
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)
        rng = DateRangeInfo(date_from=d_from, date_to=d_to, label=label)

        totals = await ReportRepository.get_sales_totals(db, tenant_id, d_from, d_to)
        if totals["bill_count"] == 0:
            return InsightsResponse(
                range=rng, module="business", data_available=False,
                insights=[InsightItem(
                    id="no_business_data", category="coverage", severity="info",
                    title="No sales in this period",
                    detail="No completed sales were recorded in the selected range, so no business "
                           "analytics can be computed.",
                    evidence={"revenue": 0, "bill_count": 0},
                )],
                note="Insufficient data for the selected range.",
            )

        insights: list = [InsightItem(
            id="revenue_overview", category="revenue", severity="positive",
            title="Sales in this period",
            detail=f"{totals['bill_count']} completed sale(s) totalling {totals['revenue']} "
                   f"across {totals['customer_count']} registered customer(s).",
            evidence=totals,
        )]

        top_products = await TopProductsService.get_top_products(db, current_user, d_from, d_to, "revenue", 1)
        if top_products["items"]:
            tp = top_products["items"][0]
            insights.append(InsightItem(
                id="top_product", category="product", severity="info",
                title="Top-selling product",
                detail=f"{tp['product_name']} led sales with {tp['units']} unit(s) and "
                       f"{tp['revenue']} in revenue.",
                evidence={"product_code": tp["product_code"], "units": tp["units"], "revenue": tp["revenue"]},
            ))

        # Top customers by spend — fetched once (top 10) and reused for both the
        # single top-customer insight and the birthday scan (no new ranking).
        top_customers = await ReportRepository.get_top_customers_by_sales(db, tenant_id, d_from, d_to, 10)
        if top_customers:
            tc = top_customers[0]
            insights.append(InsightItem(
                id="top_customer", category="customer", severity="info",
                title="Top customer by spend",
                detail=f"{tc['customer_name'] or 'A customer'} spent {tc['total_spent']} across "
                       f"{tc['bill_count']} bill(s) — a candidate for loyalty recognition.",
                evidence=tc,
            ))
            birthday = await ReportService._birthday_insight(
                db, tenant_id, top_customers, _today_ist(), "business"
            )
            if birthday:
                insights.append(birthday)

        return InsightsResponse(range=rng, module="business", data_available=True, insights=insights)

    @staticmethod
    async def get_scheme_insights(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> InsightsResponse:
        """Data-grounded scheme insights, from real enrollment/collection
        aggregates. Invents nothing when the range has no scheme activity."""
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)
        rng = DateRangeInfo(date_from=d_from, date_to=d_to, label=label)

        pay = await ReportRepository.get_payment_totals(db, tenant_id, d_from, d_to)
        status_counts = await ReportRepository.get_enrollment_status_counts(db, tenant_id)
        active = status_counts[STATUS_ACTIVE]
        completed = status_counts[STATUS_COMPLETED]
        cancelled = status_counts[STATUS_CANCELLED]
        total_decided = active + completed + cancelled

        if total_decided == 0 and pay["success_count"] == 0:
            return InsightsResponse(
                range=rng, module="scheme", data_available=False,
                insights=[InsightItem(
                    id="no_scheme_data", category="coverage", severity="info",
                    title="No scheme activity",
                    detail="No enrollments or scheme collections exist for this range, so no scheme "
                           "analytics can be computed.",
                    evidence={"enrollments": 0, "collections": 0},
                )],
                note="Insufficient data for the selected range.",
            )

        insights: list = []
        group_by_month = (d_to - d_from).days > 31
        trend = await ReportRepository.get_new_enrollment_trend(db, tenant_id, d_from, d_to, group_by_month)
        new_in_range = sum(r["new_enrollments"] for r in trend)
        insights.append(InsightItem(
            id="enrollment_activity", category="enrollment", severity="positive" if new_in_range else "info",
            title="Enrollment activity",
            detail=f"{new_in_range} new enrollment(s) in the period; {active} currently active.",
            evidence={"new_enrollments": new_in_range, "active": active,
                      "completed": completed, "cancelled": cancelled},
        ))

        if total_decided:
            retention = round(((active + completed) / total_decided) * 100, 1)
            insights.append(InsightItem(
                id="retention", category="retention",
                severity="warning" if retention < 50 else "positive",
                title="Retention rate",
                detail=f"{retention}% of decided enrollments are active or completed "
                       f"(rather than cancelled).",
                evidence={"retention_rate_percent": retention, "cancelled": cancelled},
            ))

        insights.append(InsightItem(
            id="scheme_collections", category="collections",
            severity="positive" if pay["success_amount"] > 0 else "info",
            title="Scheme collections",
            detail=f"{pay['success_amount']} collected across {pay['success_count']} successful "
                   f"contribution(s) in the period.",
            evidence={"success_amount": pay["success_amount"], "success_count": pay["success_count"]},
        ))

        # Top scheme customers by investment — fetched once (top 10) and reused
        # for the single top-customer insight and the birthday scan.
        top = await ReportRepository.get_top_enrollments_by_investment(db, tenant_id, d_from, d_to, 10)
        if top:
            t = top[0]
            insights.append(InsightItem(
                id="top_scheme_customer", category="customer", severity="info",
                title="Top scheme customer",
                detail=f"{t['customer_name']} invested {t['total_invested']} in "
                       f"{t['scheme_name']} — a candidate for loyalty recognition.",
                evidence={"customer_id": t["customer_id"], "scheme_name": t["scheme_name"],
                          "total_invested": t["total_invested"]},
            ))
            birthday = await ReportService._birthday_insight(
                db, tenant_id, top, _today_ist(), "scheme"
            )
            if birthday:
                insights.append(birthday)

        return InsightsResponse(range=rng, module="scheme", data_available=True, insights=insights)

    # ─── Enrollments ───

    @staticmethod
    async def get_enrollment_summary(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> EnrollmentSummaryResponse:
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)

        status_counts = await ReportRepository.get_enrollment_status_counts(db, tenant_id)
        active = status_counts[STATUS_ACTIVE]
        completed = status_counts[STATUS_COMPLETED]
        cancelled = status_counts[STATUS_CANCELLED]
        total_decided = active + completed + cancelled
        retention = round(((active + completed) / total_decided) * 100, 1) if total_decided else None

        group_by_month = (d_to - d_from).days > 31
        trend_rows = await ReportRepository.get_new_enrollment_trend(db, tenant_id, d_from, d_to, group_by_month)
        new_in_range = sum(r["new_enrollments"] for r in trend_rows)

        return EnrollmentSummaryResponse(
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            active_count=active,
            completed_count=completed,
            cancelled_count=cancelled,
            new_enrollments_in_range=new_in_range,
            retention_rate_percent=retention,
            conversion_funnel_percent=None,
            redemption_velocity_days=None,
            daily_trend=[
                EnrollmentTrendPoint(
                    period_label=_label_bucket(row["bucket"], group_by_month),
                    new_enrollments=row["new_enrollments"],
                    maturity_amount=round(row.get("maturity_amount", 0.0), 2),
                )
                for row in trend_rows
            ],
        )

    # ─── Gold Rate ───

    @staticmethod
    async def get_gold_rate_trend(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> GoldRateTrendResponse:
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)

        rows = await ReportRepository.get_gold_rate_trend(db, tenant_id, d_from, d_to)

        # Day-over-day change between the two most recent rate points in range —
        # post-processing of already-fetched rows, not a new query.
        latest_change: Optional[float] = None
        if len(rows) >= 2:
            latest_change = _growth_percent(rows[-1]["rate_24k"], rows[-2]["rate_24k"])

        return GoldRateTrendResponse(
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            trend=[GoldRateTrendPoint(date=row["date"], rate_24k=row["rate_24k"]) for row in rows],
            latest_change_percent=latest_change,
        )

    # ─── Schemes ───

    @staticmethod
    async def get_scheme_summary(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> SchemeSummaryResponse:
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)

        rows = await ReportRepository.get_scheme_summary(db, tenant_id, d_from, d_to)

        return SchemeSummaryResponse(
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            schemes=[SchemeSummaryItem(**row) for row in rows],
        )

    # ─── Dashboard (composed, reusable foundation — see schema docstring) ───

    @staticmethod
    async def get_dashboard_summary(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> DashboardSummaryResponse:
        tenant_id = ReportService._require_tenant(current_user)
        d_from, d_to, label = _resolve_range(period, date_from, date_to)
        prev_from, prev_to = _previous_range(d_from, d_to)

        current_payments = await ReportRepository.get_payment_totals(db, tenant_id, d_from, d_to)
        previous_payments = await ReportRepository.get_payment_totals(db, tenant_id, prev_from, prev_to)
        status_counts = await ReportRepository.get_enrollment_status_counts(db, tenant_id)
        gold = await ReportRepository.get_gold_accumulation_total(db, tenant_id, d_from, d_to)
        current_customers = await ReportRepository.get_customer_count(db, tenant_id, _end_of_day_ist(d_to))
        previous_customers = await ReportRepository.get_customer_count(db, tenant_id, _end_of_day_ist(prev_to))

        return DashboardSummaryResponse(
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            total_revenue=current_payments["success_amount"],
            total_revenue_growth_percent=_growth_percent(
                current_payments["success_amount"], previous_payments["success_amount"]
            ),
            active_enrollments=status_counts[STATUS_ACTIVE],
            total_gold_accumulated_grams=gold["total_gold_weight_grams"],
            outstanding_dues=current_payments["pending_amount"],
            total_customers=current_customers,
            total_customers_growth_percent=_growth_percent(current_customers, previous_customers),
        )

    # ─── Export (Module 15 — reuses the methods above, no duplicated queries) ───
    # Each method below fetches data through the exact same service call the
    # corresponding page already makes for on-screen display, then shapes the
    # result into (columns, rows) for the shared ExportService. No aggregation
    # or business logic is reimplemented here.

    @staticmethod
    async def export_reports_summary(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
        limit: int,
        fmt: ExportFormat,
    ) -> ExportFileResponse:
        """Admin Reports page export — the Top Customers table, the only
        genuinely tabular data on that page (KPI cards don't decompose into
        export rows). Both of the page's Excel buttons feed this."""
        data = await ReportService.get_top_customers(db, current_user, period, date_from, date_to, limit)
        columns = [
            ExportColumn("customer_name", "Customer Name"),
            ExportColumn("scheme_name", "Scheme"),
            ExportColumn("enrollment_status", "Status"),
            ExportColumn("total_invested", "Total Invested (INR)"),
            ExportColumn("gold_weight_grams", "Gold Accumulated (g)"),
        ]
        rows = [c.model_dump() for c in data.customers]
        stem = f"DFX_Solution_Reports_TopCustomers_{data.range.date_from.isoformat()}_to_{data.range.date_to.isoformat()}"
        return ExportService.generate(rows, columns, fmt, stem)

    @staticmethod
    async def export_analytics_summary(
        db: AsyncSession,
        current_user: User,
        fmt: ExportFormat,
    ) -> ExportFileResponse:
        """Admin Analytics page export — the same 4 KPI values the page
        displays, fetched with the exact same fixed periods the page itself
        uses (this_month for payment data, this_week for enrollment data)."""
        payments = await ReportService.get_payment_summary(db, current_user, "this_month", None, None)
        enrollments = await ReportService.get_enrollment_summary(db, current_user, "this_week", None, None)

        rows = [
            {"metric": "Conversion Funnel (%)", "value": enrollments.conversion_funnel_percent},
            {"metric": "Scheme Retention (%)", "value": enrollments.retention_rate_percent},
            {"metric": "Avg Installment Size (INR, This Month)", "value": payments.avg_installment_amount},
            {"metric": "Redemption Velocity (Days)", "value": enrollments.redemption_velocity_days},
        ]
        for row in rows:
            if row["value"] is None:
                row["value"] = "Not available"
        columns = [ExportColumn("metric", "Metric"), ExportColumn("value", "Value")]
        stem = f"DFX_Solution_Analytics_Summary_{_today_ist().isoformat()}"
        return ExportService.generate(rows, columns, fmt, stem)

    @staticmethod
    async def export_dashboard_summary(
        db: AsyncSession,
        current_user: User,
        fmt: ExportFormat,
    ) -> ExportFileResponse:
        """Admin Dashboard export — the core today-scoped KPI snapshot from
        get_dashboard_summary. Exports the flow-KPI snapshot only, not the
        page's separate all-time gold/pending-installment figures (those use
        a different, wide custom date range purely to express "all time" —
        see SESSION_HANDOFF.md Module 13); keeping this to one existing call
        avoids re-implementing the page's own multi-call orchestration here."""
        data = await ReportService.get_dashboard_summary(db, current_user, "today", None, None)
        rows = [
            {"metric": "Total Revenue (INR, Today)", "value": data.total_revenue},
            {"metric": "Total Revenue Growth (%)", "value": data.total_revenue_growth_percent},
            {"metric": "Active Savings Schemes (Enrollments)", "value": data.active_enrollments},
            {"metric": "Gold Accumulated (g, Today)", "value": data.total_gold_accumulated_grams},
            {"metric": "Outstanding Dues (INR, Today)", "value": data.outstanding_dues},
            {"metric": "Total Customers", "value": data.total_customers},
            {"metric": "Total Customers Growth (%)", "value": data.total_customers_growth_percent},
        ]
        for row in rows:
            if row["value"] is None:
                row["value"] = "Not available"
        columns = [ExportColumn("metric", "Metric"), ExportColumn("value", "Value")]
        stem = f"DFX_Solution_Admin_Dashboard_{_today_ist().isoformat()}"
        return ExportService.generate(rows, columns, fmt, stem)


# ─── Phase 6 — Top Products ───
from datetime import time as _time  # noqa: E402
from app.repositories.report_repository import TopProductsRepository  # noqa: E402
from app.services.billing_service import _is_privileged  # noqa: E402

_TOP_METRICS = {"revenue", "quantity", "weight", "profit"}


class TopProductsService:
    @staticmethod
    async def get_top_products(
        db: AsyncSession, current_user: User, date_from: date, date_to: date,
        metric: str = "revenue", limit: int = 10,
    ) -> dict:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        if metric not in _TOP_METRICS:
            raise ValidationException(f"Invalid metric '{metric}'")
        if date_from > date_to:
            raise ValidationException("date_from must not be after date_to")
        limit = max(1, min(limit, 100))

        privileged = _is_privileged(current_user)
        # Profit is a privileged figure — Staff may neither rank by it nor see it.
        if metric == "profit" and not privileged:
            raise ForbiddenException("Profit ranking requires elevated privileges")

        start = datetime.combine(date_from, _time.min, tzinfo=IST)
        end = datetime.combine(date_to, _time.max, tzinfo=IST)
        rows = await TopProductsRepository.aggregate(
            db, current_user.tenant_id, start, end, metric, limit
        )
        items = []
        for r in rows:
            item = {
                "product_code": r.product_code,
                "product_name": r.product_name,
                "units": int(r.units),
                "revenue": round(float(r.revenue), 2),
                "gold_weight_grams": round(float(r.gold_weight), 3),
            }
            # Never leak profit to a non-privileged caller.
            item["profit"] = round(float(r.profit), 2) if privileged else None
            items.append(item)
        return {
            "metric": metric,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "profit_visible": privileged,
            "items": items,
        }


# ─── Phase 8 — Dashboard operational cards ───
from datetime import date as _date  # noqa: E402
from sqlalchemy import select as _select, func as _func  # noqa: E402
from app.models.auth import User as _User, Role as _Role  # noqa: E402
from app.models.billing import InventoryItem as _Item  # noqa: E402
from app.core.constants import ROLE_CUSTOMER as _ROLE_CUSTOMER, STOCK_STATUS_RETURNED_PENDING_INSPECTION as _PENDING_INSP, STOCK_STATUS_IN_STOCK as _IN_STOCK  # noqa: E402
from app.repositories.collection_repository import CollectionRepository as _CollRepo  # noqa: E402
from app.services.collection_service import REMINDER_WINDOW_DAYS as _WINDOW  # noqa: E402


class DashboardCardsService:
    @staticmethod
    async def get_cards(db: AsyncSession, current_user: User) -> dict:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        t = current_user.tenant_id

        overdue = len(await _CollRepo.list_overdue_active(db, _date.today(), _WINDOW, t))

        pending_kyc = int((await db.execute(
            _select(_func.count(_User.id))
            .join(_Role, _User.role_id == _Role.id)
            .where(_User.tenant_id == t, _Role.name == _ROLE_CUSTOMER, _User.kyc_status == "Pending")
        )).scalar_one())

        pending_inspection = int((await db.execute(
            _select(_func.count(_Item.id))
            .where(_Item.tenant_id == t, _Item.stock_status == _PENDING_INSP)
        )).scalar_one())

        # Honest inventory metric — the data model has no quantity/reorder
        # threshold, so there is no true "low stock"; we surface the sellable
        # (IN_STOCK) item count instead.
        items_in_stock = int((await db.execute(
            _select(_func.count(_Item.id))
            .where(_Item.tenant_id == t, _Item.stock_status == _IN_STOCK)
        )).scalar_one())

        return {
            "overdue_enrollments": overdue,
            "pending_kyc": pending_kyc,
            "pending_inspection": pending_inspection,
            "items_in_stock": items_in_stock,
        }
