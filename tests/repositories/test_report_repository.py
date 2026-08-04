"""
JROS Repository Tests — ReportRepository
============================================

Covers:
  - get_payment_totals
  - get_payment_trend
  - get_top_enrollments_by_investment
  - get_enrollment_status_counts
  - get_new_enrollment_trend
  - get_gold_rate_trend
  - get_gold_accumulation_total
  - get_scheme_summary
  - get_customer_count
"""

import uuid
from datetime import date, timedelta, datetime, timezone
from app.models.scheme import Scheme
from app.models.enrollment import SchemeEnrollment
from app.models.payment import Payment
from app.models.passbook import PassbookEntry
from app.models.goldrate import GoldRate
from app.repositories.scheme_repository import SchemeRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.goldrate_repository import GoldRateRepository
from app.repositories.report_repository import ReportRepository

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


async def _create_enrollment(db_session, admin_user, customer_user, scheme, status="ACTIVE", joined_date=None) -> SchemeEnrollment:
    enrollment = SchemeEnrollment(
        id=f"enr_test_{uuid.uuid4().hex[:12]}",
        tenant_id=admin_user.tenant_id,
        customer_id=customer_user.id,
        scheme_id=scheme.id,
        enrollment_number=f"ENR-TEST-{uuid.uuid4().hex[:6].upper()}",
        joined_date=joined_date or TODAY,
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


async def _create_passbook_entry(db_session, admin_user, enrollment, gold_weight, entry_number=1) -> PassbookEntry:
    entry = PassbookEntry(
        id=f"pb_test_{uuid.uuid4().hex[:12]}",
        tenant_id=admin_user.tenant_id,
        enrollment_id=enrollment.id,
        entry_number=entry_number,
        entry_date=TODAY,
        description="Test entry",
        amount=1000.0,
        gold_rate=6000.0,
        gold_weight=gold_weight,
        running_installment_count=entry_number,
        created_by=admin_user.id,
    )
    db_session.add(entry)
    await db_session.commit()
    return entry


class TestPaymentTotals:

    async def test_sums_success_and_pending_separately(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY, "SUCCESS")
        await _create_payment(db_session, admin_user, enrollment, 500.0, TODAY, "SUCCESS")
        await _create_payment(db_session, admin_user, enrollment, 300.0, TODAY, "PENDING")

        result = await ReportRepository.get_payment_totals(db_session, admin_user.tenant_id, TODAY, TODAY)
        assert result["success_amount"] == 1500.0
        assert result["success_count"] == 2
        assert result["pending_amount"] == 300.0
        assert result["pending_count"] == 1

    async def test_excludes_payments_outside_range(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY - timedelta(days=10), "SUCCESS")

        result = await ReportRepository.get_payment_totals(db_session, admin_user.tenant_id, TODAY, TODAY)
        assert result["success_amount"] == 0.0
        assert result["success_count"] == 0

    async def test_scoped_to_tenant(self, db_session, admin_user, customer_user, test_tenant):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY, "SUCCESS")

        result = await ReportRepository.get_payment_totals(db_session, "tnt_wrong_xyz", TODAY, TODAY)
        assert result["success_amount"] == 0.0


class TestPaymentTrend:

    async def test_groups_by_day(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY, "SUCCESS")
        await _create_payment(db_session, admin_user, enrollment, 500.0, TODAY - timedelta(days=1), "SUCCESS")

        rows = await ReportRepository.get_payment_trend(
            db_session, admin_user.tenant_id, TODAY - timedelta(days=1), TODAY, group_by_month=False
        )
        assert len(rows) == 2
        totals = {r["bucket"]: r["total_amount"] for r in rows}
        assert totals[TODAY] == 1000.0
        assert totals[TODAY - timedelta(days=1)] == 500.0

    async def test_groups_by_month(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, date(2026, 6, 5), "SUCCESS")
        await _create_payment(db_session, admin_user, enrollment, 500.0, date(2026, 6, 20), "SUCCESS")
        await _create_payment(db_session, admin_user, enrollment, 700.0, date(2026, 7, 5), "SUCCESS")

        rows = await ReportRepository.get_payment_trend(
            db_session, admin_user.tenant_id, date(2026, 6, 1), date(2026, 7, 31), group_by_month=True
        )
        assert len(rows) == 2
        amounts = sorted(r["total_amount"] for r in rows)
        assert amounts == [700.0, 1500.0]


class TestTopEnrollmentsByInvestment:

    async def test_orders_by_total_invested_desc(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enr_low = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        enr_high = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enr_low, 500.0, TODAY, "SUCCESS")
        await _create_payment(db_session, admin_user, enr_high, 2000.0, TODAY, "SUCCESS")

        rows = await ReportRepository.get_top_enrollments_by_investment(
            db_session, admin_user.tenant_id, TODAY, TODAY, limit=10
        )
        assert len(rows) == 2
        assert rows[0]["enrollment_id"] == enr_high.id
        assert rows[0]["total_invested"] == 2000.0
        assert rows[1]["enrollment_id"] == enr_low.id

    async def test_includes_gold_weight_from_passbook(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY, "SUCCESS")
        await _create_passbook_entry(db_session, admin_user, enrollment, 1.5)

        rows = await ReportRepository.get_top_enrollments_by_investment(
            db_session, admin_user.tenant_id, TODAY, TODAY, limit=10
        )
        assert rows[0]["gold_weight_grams"] == 1.5

    async def test_zero_gold_weight_when_no_passbook_entries(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_payment(db_session, admin_user, enrollment, 1000.0, TODAY, "SUCCESS")

        rows = await ReportRepository.get_top_enrollments_by_investment(
            db_session, admin_user.tenant_id, TODAY, TODAY, limit=10
        )
        assert rows[0]["gold_weight_grams"] == 0.0

    async def test_respects_limit(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        for _ in range(3):
            enr = await _create_enrollment(db_session, admin_user, customer_user, scheme)
            await _create_payment(db_session, admin_user, enr, 100.0, TODAY, "SUCCESS")

        rows = await ReportRepository.get_top_enrollments_by_investment(
            db_session, admin_user.tenant_id, TODAY, TODAY, limit=2
        )
        assert len(rows) == 2


class TestEnrollmentStatusCounts:

    async def test_counts_by_status(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        await _create_enrollment(db_session, admin_user, customer_user, scheme, status="ACTIVE")
        await _create_enrollment(db_session, admin_user, customer_user, scheme, status="ACTIVE")
        await _create_enrollment(db_session, admin_user, customer_user, scheme, status="CANCELLED")

        counts = await ReportRepository.get_enrollment_status_counts(db_session, admin_user.tenant_id)
        assert counts["ACTIVE"] == 2
        assert counts["CANCELLED"] == 1
        assert counts["COMPLETED"] == 0

    async def test_empty_tenant_returns_zeros(self, db_session, test_tenant):
        counts = await ReportRepository.get_enrollment_status_counts(db_session, test_tenant.id)
        assert counts == {"ACTIVE": 0, "COMPLETED": 0, "CANCELLED": 0}


class TestNewEnrollmentTrend:

    async def test_counts_within_range_by_day(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        await _create_enrollment(db_session, admin_user, customer_user, scheme, joined_date=TODAY)
        await _create_enrollment(db_session, admin_user, customer_user, scheme, joined_date=TODAY)
        await _create_enrollment(db_session, admin_user, customer_user, scheme, joined_date=TODAY - timedelta(days=5))

        rows = await ReportRepository.get_new_enrollment_trend(
            db_session, admin_user.tenant_id, TODAY, TODAY, group_by_month=False
        )
        assert len(rows) == 1
        assert rows[0]["new_enrollments"] == 2


class TestGoldRateTrend:

    async def test_returns_rates_within_range(self, db_session, admin_user):
        rate = GoldRate(
            id=f"gr_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            rate_24k=6250.0,
            effective_date=TODAY,
            created_by=admin_user.id,
        )
        await GoldRateRepository.create_rate(db_session, rate)
        await db_session.commit()

        rows = await ReportRepository.get_gold_rate_trend(db_session, admin_user.tenant_id, TODAY, TODAY)
        assert len(rows) == 1
        assert rows[0]["rate_24k"] == 6250.0
        assert rows[0]["date"] == TODAY


class TestGoldAccumulationTotal:

    async def test_sums_gold_weight_within_range(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
        enrollment = await _create_enrollment(db_session, admin_user, customer_user, scheme)
        await _create_passbook_entry(db_session, admin_user, enrollment, 1.25, entry_number=1)
        await _create_passbook_entry(db_session, admin_user, enrollment, 0.75, entry_number=2)

        result = await ReportRepository.get_gold_accumulation_total(db_session, admin_user.tenant_id, TODAY, TODAY)
        assert result["total_gold_weight_grams"] == 2.0
        assert result["entry_count"] == 2


class TestSchemeSummary:

    async def test_reports_active_enrollments_and_collections_per_scheme(self, db_session, admin_user, customer_user):
        scheme_a = await _create_scheme(db_session, admin_user, name="Scheme A")
        scheme_b = await _create_scheme(db_session, admin_user, name="Scheme B")
        enr_a = await _create_enrollment(db_session, admin_user, customer_user, scheme_a, status="ACTIVE")
        await _create_enrollment(db_session, admin_user, customer_user, scheme_b, status="CANCELLED")
        await _create_payment(db_session, admin_user, enr_a, 1000.0, TODAY, "SUCCESS")

        rows = await ReportRepository.get_scheme_summary(db_session, admin_user.tenant_id, TODAY, TODAY)
        by_name = {r["scheme_name"]: r for r in rows}

        assert by_name["Scheme A"]["active_enrollments"] == 1
        assert by_name["Scheme A"]["total_collected"] == 1000.0
        assert by_name["Scheme B"]["active_enrollments"] == 0
        assert by_name["Scheme B"]["total_collected"] == 0.0


class TestCustomerCount:

    async def test_counts_customer_role_users_for_tenant(self, db_session, test_tenant, customer_user):
        count = await ReportRepository.get_customer_count(db_session, test_tenant.id, as_of=None)
        assert count == 1

    async def test_excludes_other_tenant(self, db_session, test_tenant, customer_user):
        count = await ReportRepository.get_customer_count(db_session, "tnt_wrong_xyz", as_of=None)
        assert count == 0

    async def test_excludes_non_customer_roles(self, db_session, test_tenant, admin_user):
        # admin_user only (no customer_user fixture used) — Admin role must not count
        count = await ReportRepository.get_customer_count(db_session, test_tenant.id, as_of=None)
        assert count == 0

    async def test_as_of_cutoff_excludes_customers_created_after_it(self, db_session, test_tenant, customer_user):
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        count = await ReportRepository.get_customer_count(db_session, test_tenant.id, as_of=yesterday)
        assert count == 0

    async def test_as_of_cutoff_includes_customers_created_before_it(self, db_session, test_tenant, customer_user):
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        count = await ReportRepository.get_customer_count(db_session, test_tenant.id, as_of=tomorrow)
        assert count == 1
