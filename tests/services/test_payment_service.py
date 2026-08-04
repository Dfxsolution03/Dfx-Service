"""
JROS Service Tests — PaymentService
=======================================
"""

import pytest
from app.models.auth import User
from app.schemas.scheme import SchemeCreateRequest
from app.schemas.enrollment import EnrollmentCreateRequest
from app.schemas.payment import PaymentManualCreateRequest, PaymentUpdateRequest
from app.services.scheme_service import SchemeService
from app.services.enrollment_service import EnrollmentService
from app.services.payment_service import PaymentService
from app.exceptions.base import ResourceNotFoundException


async def _enroll_customer(db_session, admin_user: User, customer_user: User):
    scheme = await SchemeService.create_scheme(
        db_session, admin_user, SchemeCreateRequest(name="Monthly Gold Plan", monthly_amount=1000, duration_months=11)
    )
    enrollment = await EnrollmentService.create_enrollment(
        db_session, customer_user, EnrollmentCreateRequest(scheme_id=scheme.id)
    )
    return scheme, enrollment


class TestCreateManualPayment:

    async def test_defaults_to_success_status(self, db_session, admin_user: User, customer_user: User):
        _, enrollment = await _enroll_customer(db_session, admin_user, customer_user)

        result = await PaymentService.create_manual_payment(
            db_session, admin_user,
            PaymentManualCreateRequest(enrollment_id=enrollment.id, amount=1000, payment_method="CASH"),
        )
        assert result.payment_status == "SUCCESS"
        assert result.passbook_entry_id is None
        assert result.gateway_name is None

    async def test_explicit_status_respected(self, db_session, admin_user: User, customer_user: User):
        _, enrollment = await _enroll_customer(db_session, admin_user, customer_user)

        result = await PaymentService.create_manual_payment(
            db_session, admin_user,
            PaymentManualCreateRequest(enrollment_id=enrollment.id, amount=1000, payment_method="CHEQUE", payment_status="PENDING"),
        )
        assert result.payment_status == "PENDING"

    async def test_nonexistent_enrollment_raises(self, db_session, admin_user: User):
        with pytest.raises(ResourceNotFoundException):
            await PaymentService.create_manual_payment(
                db_session, admin_user,
                PaymentManualCreateRequest(enrollment_id="enr_does_not_exist", amount=1000, payment_method="CASH"),
            )


class TestUpdatePayment:

    async def test_update_not_found_raises(self, db_session, admin_user: User):
        with pytest.raises(ResourceNotFoundException):
            await PaymentService.update_payment(
                db_session, admin_user, "pay_does_not_exist", PaymentUpdateRequest(remarks="x")
            )

    async def test_update_modifies_fields(self, db_session, admin_user: User, customer_user: User):
        _, enrollment = await _enroll_customer(db_session, admin_user, customer_user)
        created = await PaymentService.create_manual_payment(
            db_session, admin_user,
            PaymentManualCreateRequest(enrollment_id=enrollment.id, amount=1000, payment_method="CASH"),
        )

        updated = await PaymentService.update_payment(
            db_session, admin_user, created.id, PaymentUpdateRequest(payment_status="REFUNDED")
        )
        assert updated.payment_status == "REFUNDED"
        assert updated.id == created.id


class TestGetCustomerPayments:

    async def test_returns_own_payments_only(self, db_session, admin_user: User, customer_user: User):
        _, enrollment = await _enroll_customer(db_session, admin_user, customer_user)
        created = await PaymentService.create_manual_payment(
            db_session, admin_user,
            PaymentManualCreateRequest(enrollment_id=enrollment.id, amount=1000, payment_method="CASH"),
        )

        results = await PaymentService.get_customer_payments(db_session, customer_user)
        assert len(results) == 1
        assert results[0].id == created.id


class TestPassbookIntegrationPlaceholder:

    async def test_placeholder_is_not_implemented(self, db_session, admin_user: User, customer_user: User):
        """Confirms the documented extension point exists but deliberately does nothing."""
        _, enrollment = await _enroll_customer(db_session, admin_user, customer_user)
        created = await PaymentService.create_manual_payment(
            db_session, admin_user,
            PaymentManualCreateRequest(enrollment_id=enrollment.id, amount=1000, payment_method="CASH"),
        )
        from app.repositories.payment_repository import PaymentRepository
        payment = await PaymentRepository.get_payment_by_id(db_session, created.id, admin_user.tenant_id)

        with pytest.raises(NotImplementedError):
            await PaymentService.create_passbook_entry_for_payment(db_session, payment)
