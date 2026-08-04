"""
JROS Service Tests — ReportService
======================================

Covers:
  - _resolve_range / _growth_percent / _label_bucket (pure date-math helpers)
  - get_payment_summary (avg installment calc, growth_percent, tenant guard)
  - get_enrollment_summary (retention rate calc, always-null funnel/velocity fields)
  - get_dashboard_summary (composition across payment/enrollment/gold data)
"""

import uuid
import pytest
from datetime import date, datetime, timedelta

from app.models.scheme import Scheme
from app.models.enrollment import SchemeEnrollment
from app.models.payment import Payment
from app.models.passbook import PassbookEntry
from app.models.goldrate import GoldRate
from app.repositories.scheme_repository import SchemeRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.goldrate_repository import GoldRateRepository
from app.services.report_service import ReportService, _resolve_range, _growth_percent, _label_bucket
from app.exceptions.base import ForbiddenException, ValidationException

TODAY = date(2026, 7, 15)


async def _create_scheme(db_session, admin_user, name="Test Plan") -> Scheme:
    scheme = Scheme(
        id=f"sch_test_{uuid.uuid4().hex[:12]}",
        tenant_id=admin_user.tenant_id,
        name=name,
        monthly_amount=1000.0,
        duration_months=12,
        is_active=True,
        created_by=admin_user.id,
    )
    await SchemeRepository.create_scheme(db_session, scheme)
    await db_session.commit()
    return scheme


async def _create_enrollment(db_session, admin_user, customer_user, scheme, status="ACTIVE") -> SchemeEnrollment:
    enrollment = SchemeEnrollment(
        id=f"enr_test_{uuid.uuid4().hex[:12]}",
        tenant_id=admin_user.tenant_id,
        customer_id=customer_user.id,
        scheme_id=scheme.id,
        enrollment_number=f"ENR-TEST-{uuid.uuid4().hex[:6].upper()}",
        joined_date=TODAY,
        status=status,
        maturity_date=date(2028, 1, 1),
    )
    await EnrollmentRepository.create_enrollment(db_session, enrollment)
    await db_session.commit()
    return enrollment


async def _create_payment(db_session, admin_user, enrollment, amount, payment_date, status="SUCCESS") -> Payment:
    payment = Payment(
        id=f"pay_test_{uuid.uuid4().hex[:12]}",
        tenant_id=admin_user.tenant_id,
        enrollment_id=enrollment.id,
        payment_reference=f"PAY-TEST-{uuid.uuid4().hex[:6].upper()}",
        amount=amount,
        payment_date=payment_date,
        payment_method="CASH",
        payment_status=status,
        created_by=admin_user.id,
    )
    db_session.add(payment)
    await db_session.commit()
    return payment


async def _create_passbook_entry(db_session, admin_user, enrollment, gold_weight) -> PassbookEntry:
    entry = PassbookEntry(
        id=f"pb_test_{uuid.uuid4().hex[:12]}",
        tenant_id=admin_user.tenant_id,
        enrollment_id=enrollment.id,
        entry_number=1,
        entry_date=TODAY,
        description="Test entry",
        amount=1000.0,
        gold_rate=6000.0,
        gold_weight=gold_weight,
        running_installment_count=1,
        created_by=admin_user.id,
    )
    db_session.add(entry)
    await db_session.commit()
    return entry


# ═══════════════════════════════════════════════════════════
# 1. Date-math helpers (pure functions, no DB)
# ═══════════════════════════════════════════════════════════

class TestResolveRange:

    def test_period_today_returns_single_day(self):
        d_from, d_to, label = _resolve_range("today", None, None)
        assert d_from == d_to
        assert label == "Today"

    def test_period_this_week_starts_monday(self):
        d_from, d_to, label = _resolve_range("this_week", None, None)
        assert d_from.weekday() == 0
        assert d_from <= d_to
        assert label == "This Week"

    def test_period_this_month_starts_first_of_month(self):
        d_from, d_to, label = _resolve_range("this_month", None, None)
        assert d_from.day == 1
        assert label == "This Month"

    def test_period_this_year_starts_jan_1(self):
        d_from, d_to, label = _resolve_range("this_year", None, None)
        assert d_from.month == 1 and d_from.day == 1
        assert label == "This Year"

    def test_default_period_is_this_month(self):
        d_from, d_to, label = _resolve_range(None, None, None)
        assert d_from.day == 1
        assert label == "This Month"

    def test_custom_range(self):
        d_from, d_to, label = _resolve_range(None, date(2026, 1, 1), date(2026, 1, 31))
        assert d_from == date(2026, 1, 1)
        assert d_to == date(2026, 1, 31)
        assert label == "Custom Range"

    def test_custom_range_overrides_period(self):
        _, _, label = _resolve_range("this_year", date(2026, 1, 1), date(2026, 1, 31))
        assert label == "Custom Range"

    def test_custom_range_missing_date_to_raises(self):
        with pytest.raises(ValidationException):
            _resolve_range(None, date(2026, 1, 1), None)

    def test_custom_range_date_from_after_date_to_raises(self):
        with pytest.raises(ValidationException):
            _resolve_range(None, date(2026, 2, 1), date(2026, 1, 1))


class TestGrowthPercent:

    def test_positive_growth(self):
        assert _growth_percent(150.0, 100.0) == 50.0

    def test_negative_growth(self):
        assert _growth_percent(50.0, 100.0) == -50.0

    def test_zero_previous_returns_none(self):
        assert _growth_percent(100.0, 0.0) is None

    def test_no_change_returns_zero(self):
        assert _growth_percent(100.0, 100.0) == 0.0


class TestLabelBucket:

    def test_day_granularity_label(self):
        assert _label_bucket(date(2026, 7, 15), group_by_month=False) == "15 Jul"

    def test_month_granularity_label_from_datetime(self):
        assert _label_bucket(datetime(2026, 7, 1, 0, 0, 0), group_by_month=True) == "Jul 2026"


# ═══════════════════════════════════════════════════════════
# 2. get_payment_summary
# ═══════════════════════════════════════════════════════════

class TestPaymentSummaryService:

    async def test_computes_avg_installment_amount(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY, "SUCCESS")
        await _create_payment(db_session, admin_user, enrollment, 2000.0, TODAY, "SUCCESS")

        result = await ReportService.get_payment_summary(db_session, admin_user, None, TODAY, TODAY)
        assert result.avg_installment_amount == 1500.0
        assert result.total_revenue == 3000.0

    async def test_avg_installment_zero_when_no_success_payments(self, db_session, admin_user):
        result = await ReportService.get_payment_summary(db_session, admin_user, None, TODAY, TODAY)
        assert result.avg_installment_amount == 0.0
        assert result.total_revenue == 0.0

    async def test_growth_percent_null_when_no_previous_period_data(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY, "SUCCESS")

        result = await ReportService.get_payment_summary(db_session, admin_user, None, TODAY, TODAY)
        assert result.total_revenue_growth_percent is None

    async def test_growth_percent_computed_against_previous_equivalent_window(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        # Previous day (the equivalent-length window immediately before TODAY..TODAY)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY - timedelta(days=1), "SUCCESS")
        await _create_payment(db_session, admin_user, enrollment, 2000.0, TODAY, "SUCCESS")

        result = await ReportService.get_payment_summary(db_session, admin_user, None, TODAY, TODAY)
        assert result.total_revenue_growth_percent == 100.0

    async def test_no_tenant_context_raises_forbidden(self, db_session, superadmin_user):
        with pytest.raises(ForbiddenException):
            await ReportService.get_payment_summary(db_session, superadmin_user, "this_month", None, None)

    async def test_pending_payment_count_reflects_pending_payments(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY, "SUCCESS")
        await _create_payment(db_session, admin_user, enrollment, 300.0, TODAY, "PENDING")
        await _create_payment(db_session, admin_user, enrollment, 200.0, TODAY, "PENDING")

        result = await ReportService.get_payment_summary(db_session, admin_user, None, TODAY, TODAY)
        assert result.pending_payment_count == 2


# ═══════════════════════════════════════════════════════════
# 3. get_enrollment_summary
# ═══════════════════════════════════════════════════════════

class TestEnrollmentSummaryService:

    async def test_retention_rate_calculation(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        await _create_enrollment(db_session, admin_user, customer_user, scheme, status="ACTIVE")
        await _create_enrollment(db_session, admin_user, customer_user, scheme, status="COMPLETED")
        await _create_enrollment(db_session, admin_user, customer_user, scheme, status="CANCELLED")

        result = await ReportService.get_enrollment_summary(db_session, admin_user, "this_month", None, None)
        # (active + completed) / total = 2/3
        assert result.retention_rate_percent == pytest.approx(66.7, abs=0.1)
        assert result.active_count == 1
        assert result.completed_count == 1
        assert result.cancelled_count == 1

    async def test_retention_rate_none_when_no_enrollments(self, db_session, admin_user):
        result = await ReportService.get_enrollment_summary(db_session, admin_user, "this_month", None, None)
        assert result.retention_rate_percent is None

    async def test_conversion_funnel_and_redemption_velocity_always_null(self, db_session, admin_user):
        result = await ReportService.get_enrollment_summary(db_session, admin_user, "this_month", None, None)
        assert result.conversion_funnel_percent is None
        assert result.redemption_velocity_days is None

    async def test_no_tenant_context_raises_forbidden(self, db_session, superadmin_user):
        with pytest.raises(ForbiddenException):
            await ReportService.get_enrollment_summary(db_session, superadmin_user, "this_month", None, None)


# ═══════════════════════════════════════════════════════════
# 4. get_dashboard_summary (composition)
# ═══════════════════════════════════════════════════════════

class TestDashboardSummaryService:

    async def test_composes_payment_enrollment_and_gold_data(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme, status="ACTIVE")
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY, "SUCCESS")
        await _create_passbook_entry(db_session, admin_user, enrollment, 0.5)

        result = await ReportService.get_dashboard_summary(db_session, admin_user, None, TODAY, TODAY)
        assert result.total_revenue == 1000.0
        assert result.active_enrollments == 1
        assert result.total_gold_accumulated_grams == 0.5

    async def test_total_customers_reflects_current_count(self, db_session, admin_user, customer_user):
        # customer_user is created with a real "now" timestamp, so the cutoff
        # here must be today's real date, not the fixed historical TODAY
        # constant used elsewhere in this file for payment/enrollment date
        # filtering — otherwise the customer's created_at falls after the
        # cutoff and gets excluded.
        result = await ReportService.get_dashboard_summary(db_session, admin_user, "today", None, None)
        assert result.total_customers == 1

    async def test_total_customers_growth_null_when_no_prior_customers(self, db_session, admin_user, customer_user):
        # customer_user was just created "now" (real timestamp), which the
        # fixed TODAY=2026-07-15 window's "previous period" cutoff predates —
        # so the previous-period count is 0 and growth is null (no fabricated
        # percent), matching the same growth_percent zero-base convention
        # used everywhere else in this module.
        result = await ReportService.get_dashboard_summary(db_session, admin_user, None, TODAY, TODAY)
        assert result.total_customers_growth_percent is None


# ═══════════════════════════════════════════════════════════
# 5. get_gold_rate_trend (latest_change_percent)
# ═══════════════════════════════════════════════════════════

class TestGoldRateTrendService:

    async def test_latest_change_percent_null_with_fewer_than_two_points(self, db_session, admin_user):
        rate = GoldRate(
            id=f"gr_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            rate_24k=6000.0,
            effective_date=TODAY,
            created_by=admin_user.id,
        )
        await GoldRateRepository.create_rate(db_session, rate)
        await db_session.commit()

        result = await ReportService.get_gold_rate_trend(db_session, admin_user, None, TODAY, TODAY)
        assert result.latest_change_percent is None

    async def test_latest_change_percent_computed_between_last_two_points(self, db_session, admin_user):
        rate_yesterday = GoldRate(
            id=f"gr_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            rate_24k=6000.0,
            effective_date=TODAY - timedelta(days=1),
            created_by=admin_user.id,
        )
        rate_today = GoldRate(
            id=f"gr_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            rate_24k=6300.0,
            effective_date=TODAY,
            created_by=admin_user.id,
        )
        await GoldRateRepository.create_rate(db_session, rate_yesterday)
        await GoldRateRepository.create_rate(db_session, rate_today)
        await db_session.commit()

        result = await ReportService.get_gold_rate_trend(
            db_session, admin_user, None, TODAY - timedelta(days=1), TODAY
        )
        assert result.latest_change_percent == 5.0
