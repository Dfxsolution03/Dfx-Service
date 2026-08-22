"""
DFX Backend Tests — Phase 10: birthday / complimentary customer insights
=========================================================================

The next-birthday date math is a pure unit test; the insight-integration
scenarios use the shared async fixtures and require Postgres (TEST_DATABASE_URL).
Heavy imports are inside the test methods.
"""
import uuid
from datetime import date, timedelta

import pytest


# ───────────────────────── Pure date logic (no database) ─────────────────────────

class TestNextBirthdayDays:
    def test_inside_window(self):
        from app.services.report_service import _next_birthday_days
        today = date(2026, 6, 1)
        assert _next_birthday_days(date(1990, 6, 11), today) == 10  # 10 days away

    def test_outside_window(self):
        from app.services.report_service import _next_birthday_days
        today = date(2026, 6, 1)
        assert _next_birthday_days(date(1990, 8, 1), today) is None  # ~61 days

    def test_year_ignored(self):
        from app.services.report_service import _next_birthday_days
        today = date(2026, 6, 1)
        assert _next_birthday_days(date(1990, 6, 11), today) == \
               _next_birthday_days(date(2005, 6, 11), today) == 10

    def test_boundary_inclusive(self):
        from app.services.report_service import _next_birthday_days
        today = date(2026, 6, 1)
        assert _next_birthday_days(date(1980, 6, 1), today) == 0     # birthday today
        assert _next_birthday_days(date(1980, 7, 1), today) == 30    # exactly window edge

    def test_feb_29_non_leap_year(self):
        from app.services.report_service import _next_birthday_days
        today = date(2026, 2, 20)  # 2026 is not a leap year
        assert _next_birthday_days(date(2000, 2, 29), today) == 8    # falls back to Feb 28


# ───────────────── DB-backed integration (require Postgres) ─────────────────

async def _sale_for(db, admin, customer):
    from app.services.billing_service import InventoryService, SaleService
    from app.schemas.billing import InventoryItemCreateRequest, SaleCreateRequest
    from app.core.constants import PURITY_KARATS
    from datetime import datetime
    from app.models.goldrate import GoldRate
    from app.services.goldrate_service import IST
    db.add(GoldRate(id=f"gr_{uuid.uuid4().hex[:10]}", tenant_id=admin.tenant_id,
                    rate_24k=6000.0, effective_date=datetime.now(IST).date(), created_by=admin.id))
    await db.commit()
    code = f"PC-{uuid.uuid4().hex[:8]}"
    await InventoryService.create_item(db, admin, InventoryItemCreateRequest(
        product_code=code, product_name="Ring", category="Rings",
        purity=next(iter(PURITY_KARATS)), gross_weight_grams=10.0,
        net_gold_weight_grams=9.0, tax_rate_percent=3.0))
    await SaleService.create_sale(db, admin, SaleCreateRequest(
        product_code=code, customer_id=customer.id, customer_name=customer.name, payment_status="PAID"))


async def _set_dob(db, customer, dob):
    from sqlalchemy import select
    from app.models.auth import User
    row = (await db.execute(select(User).where(User.id == customer.id))).scalar_one()
    row.date_of_birth = dob
    await db.commit()


def _birthday_item(resp):
    return next((i for i in resp.insights if i.id == "birthday_complimentary"), None)


class TestBusinessBirthdayInsight:
    async def test_upcoming_birthday_generates_insight(self, db_session, admin_user, customer_user):
        from app.services.report_service import ReportService
        await _sale_for(db_session, admin_user, customer_user)
        # DOB 10 days from today (month/day; any birth year).
        target = date.today() + timedelta(days=10)
        await _set_dob(db_session, customer_user, date(1985, target.month, target.day))
        resp = await ReportService.get_business_insights(db_session, admin_user, "this_month", None, None)
        item = _birthday_item(resp)
        assert item is not None
        assert any(c["customer_id"] == customer_user.id for c in item.evidence["customers"])

    async def test_birthday_outside_window_excluded(self, db_session, admin_user, customer_user):
        from app.services.report_service import ReportService
        await _sale_for(db_session, admin_user, customer_user)
        target = date.today() + timedelta(days=90)
        await _set_dob(db_session, customer_user, date(1985, target.month, target.day))
        resp = await ReportService.get_business_insights(db_session, admin_user, "this_month", None, None)
        assert _birthday_item(resp) is None

    async def test_null_dob_excluded(self, db_session, admin_user, customer_user):
        from app.services.report_service import ReportService
        await _sale_for(db_session, admin_user, customer_user)
        await _set_dob(db_session, customer_user, None)
        resp = await ReportService.get_business_insights(db_session, admin_user, "this_month", None, None)
        assert _birthday_item(resp) is None

    async def test_evidence_contains_real_values(self, db_session, admin_user, customer_user):
        from app.services.report_service import ReportService
        await _sale_for(db_session, admin_user, customer_user)
        target = date.today() + timedelta(days=5)
        await _set_dob(db_session, customer_user, date(1970, target.month, target.day))
        resp = await ReportService.get_business_insights(db_session, admin_user, "this_month", None, None)
        item = _birthday_item(resp)
        assert item is not None
        c = next(c for c in item.evidence["customers"] if c["customer_id"] == customer_user.id)
        assert c["birthday"] == target.strftime("%m-%d")
        assert c["days_until_birthday"] == 5
        assert item.evidence["window_days"] == 30


class TestSchemeBirthdayInsight:
    async def test_scheme_uses_scheme_top_customers(self, db_session, admin_user, customer_user):
        from app.services.report_service import ReportService
        from app.services.scheme_service import SchemeService
        from app.services.enrollment_service import EnrollmentService
        from app.services.payment_service import PaymentService
        from app.schemas.scheme import SchemeCreateRequest, SchemeTierInput
        from app.schemas.enrollment import EnrollmentCreateRequest
        from app.schemas.payment import PaymentManualCreateRequest
        scheme = await SchemeService.create_scheme(
            db_session, admin_user,
            SchemeCreateRequest(name="Gold", monthly_amount=1000, duration_months=12,
                                tiers=[SchemeTierInput(monthly_amount=1000, duration_months=12)]))
        enr = await EnrollmentService.create_enrollment(
            db_session, customer_user,
            EnrollmentCreateRequest(scheme_id=scheme.id, scheme_tier_id=scheme.tiers[0].id))
        await PaymentService.create_manual_payment(
            db_session, admin_user,
            PaymentManualCreateRequest(enrollment_id=enr.id, amount=1000, payment_method="CASH"))
        target = date.today() + timedelta(days=7)
        await _set_dob(db_session, customer_user, date(1988, target.month, target.day))
        resp = await ReportService.get_scheme_insights(db_session, admin_user, "this_month", None, None)
        item = _birthday_item(resp)
        assert item is not None
        assert any(c["customer_id"] == customer_user.id for c in item.evidence["customers"])

    async def test_no_qualifying_birthday_no_insight(self, db_session, admin_user, customer_user):
        from app.services.report_service import ReportService
        from app.services.scheme_service import SchemeService
        from app.services.enrollment_service import EnrollmentService
        from app.services.payment_service import PaymentService
        from app.schemas.scheme import SchemeCreateRequest, SchemeTierInput
        from app.schemas.enrollment import EnrollmentCreateRequest
        from app.schemas.payment import PaymentManualCreateRequest
        scheme = await SchemeService.create_scheme(
            db_session, admin_user,
            SchemeCreateRequest(name="Gold2", monthly_amount=1000, duration_months=12,
                                tiers=[SchemeTierInput(monthly_amount=1000, duration_months=12)]))
        enr = await EnrollmentService.create_enrollment(
            db_session, customer_user,
            EnrollmentCreateRequest(scheme_id=scheme.id, scheme_tier_id=scheme.tiers[0].id))
        await PaymentService.create_manual_payment(
            db_session, admin_user,
            PaymentManualCreateRequest(enrollment_id=enr.id, amount=1000, payment_method="CASH"))
        await _set_dob(db_session, customer_user, None)  # no DOB → no birthday insight
        resp = await ReportService.get_scheme_insights(db_session, admin_user, "this_month", None, None)
        assert _birthday_item(resp) is None
