"""
JROS Repository Tests — PassbookRepository
==============================================
"""

import uuid
from datetime import date
from app.models.scheme import Scheme
from app.models.enrollment import SchemeEnrollment
from app.models.passbook import PassbookEntry
from app.repositories.scheme_repository import SchemeRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.passbook_repository import PassbookRepository


async def _create_enrollment(db_session, admin_user, customer_user):
    scheme = Scheme(
        id=f"sch_test_{uuid.uuid4().hex[:12]}",
        tenant_id=admin_user.tenant_id,
        name="Test Plan",
        monthly_amount=1000.0,
        duration_months=12,
        is_active=True,
        created_by=admin_user.id,
    )
    await SchemeRepository.create_scheme(db_session, scheme)
    await db_session.commit()

    enrollment = SchemeEnrollment(
        id=f"enr_test_{uuid.uuid4().hex[:12]}",
        tenant_id=admin_user.tenant_id,
        customer_id=customer_user.id,
        scheme_id=scheme.id,
        enrollment_number=f"ENR-TEST-{uuid.uuid4().hex[:6].upper()}",
        joined_date=date.today(),
        status="ACTIVE",
        maturity_date=date(2028, 1, 1),
    )
    await EnrollmentRepository.create_enrollment(db_session, enrollment)
    await db_session.commit()
    return scheme, enrollment


class TestPassbookRepository:

    async def test_get_entries_returns_empty_for_new_enrollment(self, db_session, admin_user, customer_user):
        _, enrollment = await _create_enrollment(db_session, admin_user, customer_user)

        entries = await PassbookRepository.get_entries_by_enrollment(db_session, enrollment.id, admin_user.tenant_id)
        assert entries == []

    async def test_create_entry_persists_and_orders_by_entry_number(self, db_session, admin_user, customer_user):
        _, enrollment = await _create_enrollment(db_session, admin_user, customer_user)

        entry2 = PassbookEntry(
            id=f"pbe_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            enrollment_id=enrollment.id,
            entry_number=2,
            entry_date=date.today(),
            description="Second installment",
            amount=1000.0,
            gold_rate=9800.0,
            gold_weight=0.102,
            running_installment_count=2,
            created_by=admin_user.id,
        )
        entry1 = PassbookEntry(
            id=f"pbe_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            enrollment_id=enrollment.id,
            entry_number=1,
            entry_date=date.today(),
            description="First installment",
            amount=1000.0,
            gold_rate=9700.0,
            gold_weight=0.103,
            running_installment_count=1,
            created_by=admin_user.id,
        )
        # Insert out of order to verify the repository sorts by entry_number, not insertion order.
        await PassbookRepository.create_entry(db_session, entry2)
        await PassbookRepository.create_entry(db_session, entry1)
        await db_session.commit()

        entries = await PassbookRepository.get_entries_by_enrollment(db_session, enrollment.id, admin_user.tenant_id)
        assert [e.entry_number for e in entries] == [1, 2]

    async def test_entries_scoped_to_enrollment(self, db_session, admin_user, customer_user):
        _, enrollment_a = await _create_enrollment(db_session, admin_user, customer_user)
        _, enrollment_b = await _create_enrollment(db_session, admin_user, customer_user)

        entry = PassbookEntry(
            id=f"pbe_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            enrollment_id=enrollment_a.id,
            entry_number=1,
            entry_date=date.today(),
            description="Installment",
            amount=1000.0,
            gold_rate=9700.0,
            gold_weight=0.103,
            running_installment_count=1,
            created_by=admin_user.id,
        )
        await PassbookRepository.create_entry(db_session, entry)
        await db_session.commit()

        entries_b = await PassbookRepository.get_entries_by_enrollment(db_session, enrollment_b.id, admin_user.tenant_id)
        assert entries_b == []
