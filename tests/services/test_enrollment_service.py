"""
JROS Service Tests — EnrollmentService
==========================================
"""

import pytest
from app.models.auth import User
from app.schemas.scheme import SchemeCreateRequest
from app.schemas.enrollment import EnrollmentCreateRequest
from app.services.scheme_service import SchemeService
from app.services.enrollment_service import EnrollmentService, _add_months
from app.exceptions.base import ResourceNotFoundException, ConflictException, ValidationException
from datetime import date


def test_add_months_basic():
    assert _add_months(date(2026, 1, 15), 11) == date(2026, 12, 15)
    assert _add_months(date(2026, 7, 29), 24) == date(2028, 7, 29)


def test_add_months_clamps_short_month():
    # Jan 31 + 1 month -> Feb has no 31st, must clamp to Feb 28/29
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


async def _create_active_scheme(db_session, admin_user):
    req = SchemeCreateRequest(name="Monthly Gold Plan", monthly_amount=1000, duration_months=11)
    return await SchemeService.create_scheme(db_session, admin_user, req)


class TestCreateEnrollment:

    async def test_create_persists_enrollment(self, db_session, admin_user: User, customer_user: User):
        scheme = await _create_active_scheme(db_session, admin_user)
        result = await EnrollmentService.create_enrollment(
            db_session, customer_user, EnrollmentCreateRequest(scheme_id=scheme.id)
        )
        assert result.scheme_id == scheme.id
        assert result.status == "ACTIVE"
        assert result.maturity_date == _add_months(result.joined_date, 11)

    async def test_create_inactive_scheme_raises(self, db_session, admin_user: User, customer_user: User):
        scheme = await _create_active_scheme(db_session, admin_user)
        await SchemeService.deactivate_scheme(db_session, admin_user, scheme.id)

        with pytest.raises(ValidationException):
            await EnrollmentService.create_enrollment(
                db_session, customer_user, EnrollmentCreateRequest(scheme_id=scheme.id)
            )

    async def test_create_nonexistent_scheme_raises(self, db_session, customer_user: User):
        with pytest.raises(ResourceNotFoundException):
            await EnrollmentService.create_enrollment(
                db_session, customer_user, EnrollmentCreateRequest(scheme_id="sch_does_not_exist")
            )

    async def test_create_duplicate_raises_conflict(self, db_session, admin_user: User, customer_user: User):
        scheme = await _create_active_scheme(db_session, admin_user)
        await EnrollmentService.create_enrollment(db_session, customer_user, EnrollmentCreateRequest(scheme_id=scheme.id))

        with pytest.raises(ConflictException):
            await EnrollmentService.create_enrollment(db_session, customer_user, EnrollmentCreateRequest(scheme_id=scheme.id))


class TestGetCustomerEnrollments:

    async def test_returns_own_enrollments_only(self, db_session, admin_user: User, customer_user: User):
        scheme = await _create_active_scheme(db_session, admin_user)
        created = await EnrollmentService.create_enrollment(
            db_session, customer_user, EnrollmentCreateRequest(scheme_id=scheme.id)
        )

        results = await EnrollmentService.get_customer_enrollments(db_session, customer_user)
        assert len(results) == 1
        assert results[0].id == created.id


class TestAdminGetEnrollments:

    async def test_list_includes_derived_names(self, db_session, admin_user: User, customer_user: User):
        scheme = await _create_active_scheme(db_session, admin_user)
        await EnrollmentService.create_enrollment(db_session, customer_user, EnrollmentCreateRequest(scheme_id=scheme.id))

        results = await EnrollmentService.get_enrollments(db_session, admin_user)
        assert len(results) == 1
        assert results[0].scheme_name == scheme.name
        assert results[0].customer_name == customer_user.name

    async def test_get_by_id_not_found_raises(self, db_session, admin_user: User):
        with pytest.raises(ResourceNotFoundException):
            await EnrollmentService.get_enrollment_by_id(db_session, admin_user, "enr_does_not_exist")
