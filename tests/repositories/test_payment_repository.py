"""
JROS Repository Tests — PaymentRepository
=============================================
"""

import uuid
from datetime import date
from app.models.scheme import Scheme
from app.models.enrollment import SchemeEnrollment
from app.models.payment import Payment
from app.repositories.scheme_repository import SchemeRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.payment_repository import PaymentRepository


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


class TestPaymentRepository:

    async def test_get_payments_by_tenant_returns_empty_initially(self, db_session, admin_user):
        result = await PaymentRepository.get_payments_by_tenant(db_session, admin_user.tenant_id)
        assert result == []

    async def test_create_and_get_by_id(self, db_session, admin_user, customer_user):
        _, enrollment = await _create_enrollment(db_session, admin_user, customer_user)
        payment = Payment(
            id=f"pay_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            enrollment_id=enrollment.id,
            payment_reference=f"PAY-TEST-{uuid.uuid4().hex[:6].upper()}",
            amount=1000.0,
            payment_date=date.today(),
            payment_method="CASH",
            payment_status="SUCCESS",
            created_by=admin_user.id,
        )
        await PaymentRepository.create_payment(db_session, payment)
        await db_session.commit()

        fetched = await PaymentRepository.get_payment_by_id(db_session, payment.id, admin_user.tenant_id)
        assert fetched is not None
        assert fetched.enrollment.scheme.name == "Test Plan"
        assert fetched.enrollment.customer.id == customer_user.id

    async def test_get_payments_by_customer_scoped_via_enrollment_join(self, db_session, admin_user, customer_user):
        _, enrollment = await _create_enrollment(db_session, admin_user, customer_user)
        payment = Payment(
            id=f"pay_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            enrollment_id=enrollment.id,
            payment_reference=f"PAY-TEST-{uuid.uuid4().hex[:6].upper()}",
            amount=1000.0,
            payment_date=date.today(),
            payment_method="CASH",
            payment_status="SUCCESS",
            created_by=admin_user.id,
        )
        await PaymentRepository.create_payment(db_session, payment)
        await db_session.commit()

        results = await PaymentRepository.get_payments_by_customer(db_session, admin_user.tenant_id, customer_user.id)
        assert len(results) == 1
        assert results[0].id == payment.id

        # admin_user is not the customer on this enrollment — must see nothing
        empty = await PaymentRepository.get_payments_by_customer(db_session, admin_user.tenant_id, admin_user.id)
        assert empty == []

    async def test_get_payment_by_id_for_customer_excludes_other_customers(self, db_session, admin_user, customer_user):
        _, enrollment = await _create_enrollment(db_session, admin_user, customer_user)
        payment = Payment(
            id=f"pay_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            enrollment_id=enrollment.id,
            payment_reference=f"PAY-TEST-{uuid.uuid4().hex[:6].upper()}",
            amount=1000.0,
            payment_date=date.today(),
            payment_method="CASH",
            payment_status="SUCCESS",
            created_by=admin_user.id,
        )
        await PaymentRepository.create_payment(db_session, payment)
        await db_session.commit()

        result = await PaymentRepository.get_payment_by_id_for_customer(
            db_session, payment.id, admin_user.tenant_id, admin_user.id
        )
        assert result is None
