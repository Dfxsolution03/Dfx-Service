"""
DFX Backend Tests — Phase 6: Analytics & AI insights
====================================================

Pure-schema tests need no database. The service tests use the shared async
fixtures and require Postgres (TEST_DATABASE_URL). Heavy imports are inside the
test methods.
"""
import uuid

import pytest

from app.schemas.report import (
    InsightItem,
    InsightsResponse,
    TopCustomerBySalesItem,
    DateRangeInfo,
)


# ───────────────────────── Pure schema tests (no database) ─────────────────────────

class TestInsightSchemas:
    def test_insight_item_defaults(self):
        i = InsightItem(id="x", category="revenue", title="T", detail="D")
        assert i.severity == "info"
        assert i.evidence == {}

    def test_insight_bad_severity_rejected(self):
        with pytest.raises(Exception):
            InsightItem(id="x", category="c", title="t", detail="d", severity="bogus")

    def test_insights_response_no_data_carries_no_metrics(self):
        r = InsightsResponse(
            range=DateRangeInfo(date_from="2026-01-01", date_to="2026-01-31", label="Jan"),
            module="business", data_available=False,
            insights=[InsightItem(id="no_business_data", category="coverage", title="None",
                                  detail="No sales", evidence={"revenue": 0, "bill_count": 0})],
            note="Insufficient data for the selected range.",
        )
        assert r.data_available is False
        assert r.module == "business"
        assert r.insights[0].evidence["revenue"] == 0

    def test_top_customer_by_sales_item(self):
        t = TopCustomerBySalesItem(customer_id="c1", customer_name="A", total_spent=1200.0, bill_count=3)
        assert t.total_spent == 1200.0


# ───────────────────── DB-backed integration tests (require Postgres) ─────────────────────

async def _sell(db, admin, *, category="Rings", customer_id=None):
    from app.services.billing_service import InventoryService, SaleService
    from app.schemas.billing import InventoryItemCreateRequest, SaleCreateRequest
    from app.core.constants import PURITY_KARATS
    from datetime import datetime
    from app.models.goldrate import GoldRate
    from app.services.goldrate_service import IST
    # Ensure today's rate exists (idempotent enough for a test tenant).
    db.add(GoldRate(id=f"gr_{uuid.uuid4().hex[:10]}", tenant_id=admin.tenant_id,
                    rate_24k=6000.0, effective_date=datetime.now(IST).date(), created_by=admin.id))
    await db.commit()
    purity = next(iter(PURITY_KARATS))
    code = f"PC-{uuid.uuid4().hex[:8]}"
    await InventoryService.create_item(db, admin, InventoryItemCreateRequest(
        product_code=code, product_name="Ring", category=category, purity=purity,
        gross_weight_grams=10.0, net_gold_weight_grams=9.0, tax_rate_percent=3.0,
    ))
    return await SaleService.create_sale(db, admin, SaleCreateRequest(
        product_code=code, customer_id=customer_id, customer_name="Buyer", payment_status="PAID",
    ))


class TestBusinessInsights:
    async def test_no_sales_returns_data_unavailable(self, db_session, admin_user):
        from app.services.report_service import ReportService
        r = await ReportService.get_business_insights(db_session, admin_user, "today", None, None)
        assert r.data_available is False
        assert r.insights[0].id == "no_business_data"

    async def test_with_sales_grounded_in_real_totals(self, db_session, admin_user, customer_user):
        from app.services.report_service import ReportService
        await _sell(db_session, admin_user, customer_id=customer_user.id)
        r = await ReportService.get_business_insights(db_session, admin_user, "this_month", None, None)
        assert r.data_available is True
        ids = {i.id for i in r.insights}
        assert "revenue_overview" in ids
        overview = next(i for i in r.insights if i.id == "revenue_overview")
        assert overview.evidence["bill_count"] >= 1

    async def test_top_customers_by_sales(self, db_session, admin_user, customer_user):
        from app.services.report_service import ReportService
        await _sell(db_session, admin_user, customer_id=customer_user.id)
        res = await ReportService.get_top_customers_by_sales(
            db_session, admin_user, "this_month", None, None, 10
        )
        assert any(c.customer_id == customer_user.id for c in res.customers)


class TestSchemeInsights:
    async def test_no_activity_returns_data_unavailable(self, db_session, admin_user):
        from app.services.report_service import ReportService
        r = await ReportService.get_scheme_insights(db_session, admin_user, "today", None, None)
        assert r.data_available is False
        assert r.insights[0].id == "no_scheme_data"

    async def test_with_enrollment_shows_activity(self, db_session, admin_user, customer_user):
        from app.services.report_service import ReportService
        from app.services.scheme_service import SchemeService
        from app.services.enrollment_service import EnrollmentService
        from app.schemas.scheme import SchemeCreateRequest, SchemeTierInput
        from app.schemas.enrollment import EnrollmentCreateRequest
        scheme = await SchemeService.create_scheme(
            db_session, admin_user,
            SchemeCreateRequest(name="Gold", monthly_amount=1000, duration_months=12,
                                tiers=[SchemeTierInput(monthly_amount=1000, duration_months=12)]),
        )
        await EnrollmentService.create_enrollment(
            db_session, customer_user,
            EnrollmentCreateRequest(scheme_id=scheme.id, scheme_tier_id=scheme.tiers[0].id),
        )
        r = await ReportService.get_scheme_insights(db_session, admin_user, "this_month", None, None)
        assert r.data_available is True
        assert any(i.id == "enrollment_activity" for i in r.insights)
