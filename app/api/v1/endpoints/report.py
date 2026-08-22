from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_admin_or_staff_module
from app.schemas.auth import StandardSuccessResponse
from app.schemas.report import ReportPeriod
from app.schemas.export import ExportFormat
from app.services.report_service import ReportService, TopProductsService, DashboardCardsService
from app.services.collection_service import CollectionsReadService

router = APIRouter()


@router.get(
    "/collections",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Overdue Collections (Admin/Staff)",
    description="Read-only list of currently-overdue scheme installments (1..15 days, ACTIVE only), "
                "with customer/scheme/due-date/overdue-days and reminders already sent. No engine invoked.",
)
async def list_collections(
    current_user: User = Depends(require_admin_or_staff_module("reports")),
    db: AsyncSession = Depends(get_async_db),
):
    items = await CollectionsReadService.list_collections(db, current_user)
    return StandardSuccessResponse(success=True, message="Collections retrieved", data={"collections": items})


@router.get(
    "/reports/dashboard-cards",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Dashboard Operational Cards (Admin/Staff)",
    description="Live counts for the dashboard: overdue enrollments, pending KYC, pending inspection.",
)
async def get_dashboard_cards(
    current_user: User = Depends(require_admin_or_staff_module("reports")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await DashboardCardsService.get_cards(db, current_user)
    return StandardSuccessResponse(success=True, message="Dashboard cards retrieved", data=result)


@router.get(
    "/reports/top-products",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Top Products (Admin/Staff)",
    description="Ranks products over a sale-date period by revenue | quantity | weight | profit. "
                "Only COMPLETED sales count (returned/cancelled excluded). Profit is privileged.",
)
async def get_top_products(
    date_from: date = Query(...),
    date_to: date = Query(...),
    metric: str = Query("revenue", pattern="^(revenue|quantity|weight|profit)$"),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(require_admin_or_staff_module("reports")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await TopProductsService.get_top_products(db, current_user, date_from, date_to, metric, limit)
    return StandardSuccessResponse(
        success=True, message="Top products retrieved successfully", data=result,
    )


# All endpoints are reusable, general-purpose report types (not one-per-chart) —
# the Admin Reports and Admin Analytics pages each compose their view from
# whichever of these responses they need. See SESSION_HANDOFF.md Module 12.

@router.get(
    "/reports/dashboard-summary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Dashboard Summary (Admin)",
    description="Composed revenue/enrollment/gold-accumulation summary. Reserved as a reusable foundation for a future Admin Dashboard module.",
)
async def get_dashboard_summary(
    period: Optional[ReportPeriod] = Query(None, description="today | this_week | this_month | this_year"),
    date_from: Optional[date] = Query(None, description="Custom range start (requires date_to)"),
    date_to: Optional[date] = Query(None, description="Custom range end (requires date_from)"),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    data = await ReportService.get_dashboard_summary(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True,
        message="Dashboard summary retrieved successfully",
        data={"summary": data.model_dump(mode="json")},
    )


@router.get(
    "/reports/payment-summary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Payment Summary (Admin)",
    description="Revenue, outstanding dues, avg installment size, and a trend series. Feeds the Reports page KPIs/chart and the Analytics page's avg-installment KPI.",
)
async def get_payment_summary(
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    data = await ReportService.get_payment_summary(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True,
        message="Payment summary retrieved successfully",
        data={"summary": data.model_dump(mode="json")},
    )


@router.get(
    "/reports/top-customers",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Top Customers by Investment (Admin)",
    description="Ranks scheme enrollments by SUCCESS payment total within the range. Feeds the Reports page's Top Customers table.",
)
async def get_top_customers(
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    data = await ReportService.get_top_customers(db, current_user, period, date_from, date_to, limit)
    return StandardSuccessResponse(
        success=True,
        message="Top customers retrieved successfully",
        data={"report": data.model_dump(mode="json")},
    )


@router.get(
    "/reports/enrollment-summary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Enrollment Summary (Admin)",
    description="Enrollment status counts, retention rate, and a new-enrollments trend. Feeds the Reports page's Active Passbooks KPI and the Analytics page's retention KPI + weekly trend chart.",
)
async def get_enrollment_summary(
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    data = await ReportService.get_enrollment_summary(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True,
        message="Enrollment summary retrieved successfully",
        data={"summary": data.model_dump(mode="json")},
    )


@router.get(
    "/reports/gold-rate-trend",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Gold Rate Trend (Admin)",
    description="Daily 24K gold rate history for the range. Reusable foundation, not consumed by a chart in Module 12.",
)
async def get_gold_rate_trend(
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    data = await ReportService.get_gold_rate_trend(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True,
        message="Gold rate trend retrieved successfully",
        data={"report": data.model_dump(mode="json")},
    )


@router.get(
    "/reports/scheme-summary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Scheme Summary (Admin)",
    description="Per-scheme active enrollment counts and collections within the range. Reusable foundation, not consumed by a chart in Module 12.",
)
async def get_scheme_summary(
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    data = await ReportService.get_scheme_summary(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True,
        message="Scheme summary retrieved successfully",
        data={"report": data.model_dump(mode="json")},
    )


# ─── Export (Module 15) ───
# Reusable export infrastructure — see app/services/export_service.py. Each
# endpoint below fetches data through the exact same ReportService method its
# sibling display endpoint above uses, then hands it to the shared
# ExportService. No export-specific business logic lives here.

@router.get(
    "/reports/export/reports-summary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Export Reports Summary (Admin)",
    description="Downloadable Top Customers table (the same data behind /reports/top-customers) as CSV, Excel, or Markdown. Feeds the Admin Reports page's Export buttons.",
)
async def export_reports_summary(
    format: ExportFormat = Query("excel"),
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    file = await ReportService.export_reports_summary(db, current_user, period, date_from, date_to, limit, format)
    return StandardSuccessResponse(
        success=True,
        message="Export generated successfully",
        data={"export": file.model_dump(mode="json")},
    )


@router.get(
    "/reports/export/analytics-summary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Export Analytics Summary (Admin)",
    description="Downloadable KPI table (Conversion Funnel, Retention, Avg Installment Size, Redemption Velocity) as CSV, Excel, or Markdown. Feeds the Admin Analytics page's Export button.",
)
async def export_analytics_summary(
    format: ExportFormat = Query("excel"),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    file = await ReportService.export_analytics_summary(db, current_user, format)
    return StandardSuccessResponse(
        success=True,
        message="Export generated successfully",
        data={"export": file.model_dump(mode="json")},
    )


@router.get(
    "/reports/export/dashboard-summary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Export Dashboard Summary (Admin)",
    description="Downloadable today-scoped KPI table as CSV, Excel, or Markdown. Feeds the Admin Dashboard's Export Report button.",
)
async def export_dashboard_summary(
    format: ExportFormat = Query("excel"),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    file = await ReportService.export_dashboard_summary(db, current_user, format)
    return StandardSuccessResponse(
        success=True,
        message="Export generated successfully",
        data={"export": file.model_dump(mode="json")},
    )


# ─── Phase 6 — Business top customers + AI insights ───

@router.get(
    "/reports/top-customers/business",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Top Customers by Sales Spend (Admin)",
    description="Ranks registered customers by total completed-sale spend within the range — the "
                "business-side counterpart to the scheme Top Customers table.",
)
async def get_top_customers_business(
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    data = await ReportService.get_top_customers_by_sales(db, current_user, period, date_from, date_to, limit)
    return StandardSuccessResponse(
        success=True, message="Top business customers retrieved successfully",
        data={"report": data.model_dump(mode="json")},
    )


@router.get(
    "/reports/insights/business",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Business AI Insights (Admin)",
    description="Data-grounded business insights (revenue, top product, top customer) with the "
                "evidence behind each. Returns data_available=false and no invented figures when the "
                "range has no sales.",
)
async def get_business_insights(
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    data = await ReportService.get_business_insights(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True, message="Business insights retrieved successfully",
        data={"insights": data.model_dump(mode="json")},
    )


@router.get(
    "/reports/insights/scheme",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Scheme AI Insights (Admin)",
    description="Data-grounded scheme insights (enrollment activity, retention, collections, top "
                "customer) with the evidence behind each. Returns data_available=false and no invented "
                "figures when the range has no scheme activity.",
)
async def get_scheme_insights(
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("reports", "analytics")),
    db: AsyncSession = Depends(get_async_db),
):
    data = await ReportService.get_scheme_insights(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True, message="Scheme insights retrieved successfully",
        data={"insights": data.model_dump(mode="json")},
    )
