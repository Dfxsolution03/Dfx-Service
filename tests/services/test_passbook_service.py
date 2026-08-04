"""
JROS Service Tests — PassbookService
========================================
"""

import pytest
from app.models.auth import User
from app.schemas.scheme import SchemeCreateRequest
from app.schemas.enrollment import EnrollmentCreateRequest
from app.services.scheme_service import SchemeService
from app.services.enrollment_service import EnrollmentService
from app.services.passbook_service import PassbookService
from app.exceptions.base import ResourceNotFoundException


async def _enroll_customer(db_session, admin_user: User, customer_user: User):
    scheme = await SchemeService.create_scheme(
        db_session, admin_user, SchemeCreateRequest(name="Monthly Gold Plan", monthly_amount=1000, duration_months=11)
    )
    enrollment = await EnrollmentService.create_enrollment(
        db_session, customer_user, EnrollmentCreateRequest(scheme_id=scheme.id)
    )
    return scheme, enrollment


class TestGetPassbookCustomer:

    async def test_returns_empty_passbook(self, db_session, admin_user: User, customer_user: User):
        scheme, enrollment = await _enroll_customer(db_session, admin_user, customer_user)

        result = await PassbookService.get_passbook_customer(db_session, customer_user, enrollment.id)
        assert result.entries == []
        assert result.summary.entry_count == 0
        assert result.summary.total_amount_paid == 0.0
        assert result.scheme.name == "Monthly Gold Plan"
        assert result.enrollment.id == enrollment.id

    async def test_not_found_raises(self, db_session, customer_user: User):
        with pytest.raises(ResourceNotFoundException):
            await PassbookService.get_passbook_customer(db_session, customer_user, "enr_does_not_exist")

    async def test_other_customer_cannot_access(self, db_session, admin_user: User, customer_user: User):
        scheme, enrollment = await _enroll_customer(db_session, admin_user, customer_user)

        # admin_user stands in as "a different user" — must not resolve customer_user's enrollment
        with pytest.raises(ResourceNotFoundException):
            await PassbookService.get_passbook_customer(db_session, admin_user, enrollment.id)


class TestGetPassbookAdmin:

    async def test_admin_can_view_tenant_enrollment(self, db_session, admin_user: User, customer_user: User):
        scheme, enrollment = await _enroll_customer(db_session, admin_user, customer_user)

        result = await PassbookService.get_passbook_admin(db_session, admin_user, enrollment.id)
        assert result.entries == []
        assert result.enrollment.id == enrollment.id

    async def test_not_found_raises(self, db_session, admin_user: User):
        with pytest.raises(ResourceNotFoundException):
            await PassbookService.get_passbook_admin(db_session, admin_user, "enr_does_not_exist")
