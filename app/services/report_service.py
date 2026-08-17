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
