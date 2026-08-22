"""
DFX Backend Tests — Phase 9: weekly overdue reminders
=====================================================

The week-bucket formula is a pure unit test; the reminder-run scenarios use the
shared async fixtures and require Postgres (TEST_DATABASE_URL). Heavy imports
are inside the test methods.
"""
import uuid
from datetime import date, timedelta

import pytest


# ───────────────────────── Pure logic (no database) ─────────────────────────

class TestWeekIndex:
    def test_bucket_boundaries(self):
        from app.services.collection_service import _overdue_week_index
        # days 1-7 → bucket 0, 8-14 → 1, 15-21 → 2 …
        assert _overdue_week_index(1) == 0
        assert _overdue_week_index(7) == 0
        assert _overdue_week_index(8) == 1
        assert _overdue_week_index(14) == 1
        assert _overdue_week_index(15) == 2
        assert _overdue_week_index(21) == 2
        assert _overdue_week_index(22) == 3


# ───────────────── DB-backed scenarios (require Postgres) ─────────────────

async def _overdue_enrollment(db, admin, customer, days_overdue):
    """Create an ACTIVE enrollment whose next_due_date is `days_overdue` in the past."""
    from app.services.scheme_service import SchemeService
    from app.services.enrollment_service import EnrollmentService
    from app.repositories.enrollment_repository import EnrollmentRepository
    from app.schemas.scheme import SchemeCreateRequest, SchemeTierInput
    from app.schemas.enrollment import EnrollmentCreateRequest
    scheme = await SchemeService.create_scheme(
        db, admin, SchemeCreateRequest(
            name=f"Plan {uuid.uuid4().hex[:6]}", monthly_amount=1000, duration_months=12,
            tiers=[SchemeTierInput(monthly_amount=1000, duration_months=12)]),
    )
    enr = await EnrollmentService.create_enrollment(
        db, customer, EnrollmentCreateRequest(scheme_id=scheme.id, scheme_tier_id=scheme.tiers[0].id),
    )
    row = await EnrollmentRepository.get_enrollment_by_id(db, enr.id, customer.tenant_id)
    row.next_due_date = date.today() - timedelta(days=days_overdue)
    await db.commit()
    return enr.id


async def _count_reminders(db, tenant_id, enrollment_id):
    from sqlalchemy import select, func
    from app.models.collection import CollectionReminder
    stmt = select(func.count(CollectionReminder.id)).where(
        CollectionReminder.tenant_id == tenant_id,
        CollectionReminder.enrollment_id == enrollment_id,
    )
    return int((await db.execute(stmt)).scalar_one())


class TestWeeklyReminders:
    async def test_first_reminder(self, db_session, admin_user, customer_user):
        from app.services.collection_service import CollectionService
        enr = await _overdue_enrollment(db_session, admin_user, customer_user, 1)
        res = await CollectionService.run_due_reminders(db_session, today=date.today())
        assert res["sent"] >= 1
        assert await _count_reminders(db_session, admin_user.tenant_id, enr) == 1

    async def test_no_duplicate_within_week(self, db_session, admin_user, customer_user):
        from app.services.collection_service import CollectionService
        enr = await _overdue_enrollment(db_session, admin_user, customer_user, 2)
        await CollectionService.run_due_reminders(db_session, today=date.today())
        await CollectionService.run_due_reminders(db_session, today=date.today())  # same week
        assert await _count_reminders(db_session, admin_user.tenant_id, enr) == 1

    async def test_second_reminder_next_week(self, db_session, admin_user, customer_user):
        from app.services.collection_service import CollectionService
        enr = await _overdue_enrollment(db_session, admin_user, customer_user, 1)
        d0 = date.today()
        await CollectionService.run_due_reminders(db_session, today=d0)          # bucket 0
        await CollectionService.run_due_reminders(db_session, today=d0 + timedelta(days=8))  # bucket 1
        assert await _count_reminders(db_session, admin_user.tenant_id, enr) == 2

    async def test_continues_while_unpaid(self, db_session, admin_user, customer_user):
        from app.services.collection_service import CollectionService
        enr = await _overdue_enrollment(db_session, admin_user, customer_user, 1)
        d0 = date.today()
        for offset in (0, 8, 15):  # buckets 0,1,2
            await CollectionService.run_due_reminders(db_session, today=d0 + timedelta(days=offset))
        assert await _count_reminders(db_session, admin_user.tenant_id, enr) == 3

    async def test_stops_once_paid(self, db_session, admin_user, customer_user):
        from app.services.collection_service import CollectionService
        from app.repositories.enrollment_repository import EnrollmentRepository
        enr = await _overdue_enrollment(db_session, admin_user, customer_user, 1)
        d0 = date.today()
        await CollectionService.run_due_reminders(db_session, today=d0)
        # Simulate payment advancing the due date beyond today (no longer overdue).
        row = await EnrollmentRepository.get_enrollment_by_id(db_session, enr, admin_user.tenant_id)
        row.next_due_date = d0 + timedelta(days=30)
        await db_session.commit()
        await CollectionService.run_due_reminders(db_session, today=d0 + timedelta(days=8))
        assert await _count_reminders(db_session, admin_user.tenant_id, enr) == 1  # no new reminder

    async def test_multiple_installments_independent(self, db_session, admin_user, customer_user):
        from app.services.collection_service import CollectionService
        e1 = await _overdue_enrollment(db_session, admin_user, customer_user, 1)
        e2 = await _overdue_enrollment(db_session, admin_user, customer_user, 10)
        await CollectionService.run_due_reminders(db_session, today=date.today())
        assert await _count_reminders(db_session, admin_user.tenant_id, e1) == 1
        assert await _count_reminders(db_session, admin_user.tenant_id, e2) == 1

    async def test_tenant_isolation(self, db_session, admin_user, customer_user):
        from app.services.collection_service import CollectionService
        enr = await _overdue_enrollment(db_session, admin_user, customer_user, 1)
        # Run scoped to a DIFFERENT tenant → this enrollment must not be reminded.
        await CollectionService.run_due_reminders(db_session, today=date.today(), tenant_id="tnt_other")
        assert await _count_reminders(db_session, admin_user.tenant_id, enr) == 0

    async def test_push_failure_does_not_break_reminder(self, db_session, admin_user, customer_user, monkeypatch):
        from app.services.collection_service import CollectionService
        from app.services.push_service import PushService
        enr = await _overdue_enrollment(db_session, admin_user, customer_user, 1)

        async def _boom(*a, **k):
            raise RuntimeError("push provider exploded")
        monkeypatch.setattr(PushService, "send_to_user", _boom)

        res = await CollectionService.run_due_reminders(db_session, today=date.today())
        assert res["sent"] >= 1
        # In-app reminder committed despite the push blowing up.
        assert await _count_reminders(db_session, admin_user.tenant_id, enr) == 1

    async def test_existing_behavior_single_first_week(self, db_session, admin_user, customer_user):
        """Regression: within the first overdue week only one reminder exists."""
        from app.services.collection_service import CollectionService
        enr = await _overdue_enrollment(db_session, admin_user, customer_user, 3)
        await CollectionService.run_due_reminders(db_session, today=date.today())
        assert await _count_reminders(db_session, admin_user.tenant_id, enr) == 1
