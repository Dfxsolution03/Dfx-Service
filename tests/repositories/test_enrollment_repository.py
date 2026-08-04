"""
JROS Repository Tests — EnrollmentRepository
================================================
"""

import uuid
from datetime import date
from app.models.enrollment import SchemeEnrollment
from app.models.scheme import Scheme
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.scheme_repository import SchemeRepository


async def _create_scheme(db_session, admin_user):
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
    return scheme


class TestEnrollmentRepository:

    async def test_get_enrollments_by_tenant_returns_empty_initially(self, db_session, admin_user):
        result = await EnrollmentRepository.get_enrollments_by_tenant(db_session, admin_user.tenant_id)
        assert result == []

    async def test_create_and_get_by_id(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
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

        fetched = await EnrollmentRepository.get_enrollment_by_id(db_session, enrollment.id, admin_user.tenant_id)
        assert fetched is not None
        assert fetched.scheme.name == "Test Plan"
        assert fetched.customer.id == customer_user.id

    async def test_get_active_enrollment_for_scheme_detects_duplicate(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
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

        existing = await EnrollmentRepository.get_active_enrollment_for_scheme(
            db_session, admin_user.tenant_id, customer_user.id, scheme.id
        )
        assert existing is not None
        assert existing.id == enrollment.id

    async def test_customer_scoped_lookup_excludes_other_customers(self, db_session, admin_user, customer_user):
        scheme = await _create_scheme(db_session, admin_user)
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

        # admin_user's id used as a stand-in "wrong customer" — must not match
        result = await EnrollmentRepository.get_enrollment_by_id_for_customer(
            db_session, enrollment.id, admin_user.tenant_id, admin_user.id
        )
        assert result is None
