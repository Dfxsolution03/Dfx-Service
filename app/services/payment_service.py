import uuid
from datetime import date
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.payment import Payment, STATUS_SUCCESS
from app.repositories.payment_repository import PaymentRepository
from app.models.enrollment import CONTRIBUTABLE_STATUSES
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import ResourceNotFoundException, ForbiddenException, ConflictException
from app.schemas.payment import PaymentManualCreateRequest, PaymentUpdateRequest, PaymentResponse, CustomerPaymentResponse


def _generate_payment_reference() -> str:
    return f"PAY-{date.today():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _to_admin_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        tenant_id=payment.tenant_id,
        enrollment_id=payment.enrollment_id,
        enrollment_number=payment.enrollment.enrollment_number,
        customer_name=payment.enrollment.customer.name,
        scheme_name=payment.enrollment.scheme.name,
        passbook_entry_id=payment.passbook_entry_id,
        payment_reference=payment.payment_reference,
        amount=payment.amount,
        payment_date=payment.payment_date,
        payment_method=payment.payment_method,
        payment_status=payment.payment_status,
        gateway_name=payment.gateway_name,
        gateway_transaction_id=payment.gateway_transaction_id,
        remarks=payment.remarks,
        created_by=payment.created_by,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


def _to_customer_response(payment: Payment) -> CustomerPaymentResponse:
    return CustomerPaymentResponse(
        id=payment.id,
        enrollment_id=payment.enrollment_id,
        enrollment_number=payment.enrollment.enrollment_number,
        scheme_name=payment.enrollment.scheme.name,
        payment_reference=payment.payment_reference,
        amount=payment.amount,
        payment_date=payment.payment_date,
        payment_method=payment.payment_method,
        payment_status=payment.payment_status,
        remarks=payment.remarks,
    )


class PaymentService:
    # ─── Admin ───

    @staticmethod
    async def get_payments(db: AsyncSession, current_user: User) -> List[PaymentResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        payments = await PaymentRepository.get_payments_by_tenant(db, current_user.tenant_id)
        return [_to_admin_response(p) for p in payments]

    @staticmethod
    async def get_payment_by_id(db: AsyncSession, current_user: User, payment_id: str) -> PaymentResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        payment = await PaymentRepository.get_payment_by_id(db, payment_id, current_user.tenant_id)
        if not payment:
            raise ResourceNotFoundException(f"Payment ID '{payment_id}' not found")
        return _to_admin_response(payment)

    @staticmethod
    async def create_manual_payment(
        db: AsyncSession, current_user: User, req: PaymentManualCreateRequest
    ) -> PaymentResponse:
        """Admin records a payment collected outside the app (cash/bank transfer/cheque/etc.)."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        enrollment = await EnrollmentRepository.get_enrollment_by_id(
            db, req.enrollment_id, current_user.tenant_id
        )
        if not enrollment:
            raise ResourceNotFoundException(f"Enrollment ID '{req.enrollment_id}' not found")
        # Only an ACTIVE enrollment accepts new contributions. A closed, redeemed,
        # cancelled or matured scheme must not grow: its balance is already fixed
        # and may only be spent through redemption.
        if enrollment.status not in CONTRIBUTABLE_STATUSES:
            raise ConflictException(
                f"Enrollment {enrollment.enrollment_number} is {enrollment.status.lower()} and no "
                f"longer accepts contributions."
            )

        payment_id = f"pay_{uuid.uuid4().hex[:12]}"
        payment = Payment(
            id=payment_id,
            tenant_id=current_user.tenant_id,
            enrollment_id=enrollment.id,
            passbook_entry_id=None,
            payment_reference=_generate_payment_reference(),
            amount=req.amount,
            payment_date=req.payment_date or date.today(),
            payment_method=req.payment_method,
            payment_status=req.payment_status or STATUS_SUCCESS,
            gateway_name=None,
            gateway_transaction_id=None,
            remarks=req.remarks,
            created_by=current_user.id,
        )
        await PaymentRepository.create_payment(db, payment)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PAYMENT_CREATE_MANUAL",
            target_entity="payments",
            target_id=payment_id,
            before_state=None,
            after_state={
                "enrollment_id": enrollment.id,
                "amount": req.amount,
                "payment_method": req.payment_method,
                "payment_status": payment.payment_status,
            },
        )

        await db.commit()

        # NOTE: a successful manual payment deliberately does NOT create a passbook
        # entry here. See PaymentService.create_passbook_entry_for_payment below.

        refreshed = await PaymentRepository.get_payment_by_id(db, payment_id, current_user.tenant_id)
        return _to_admin_response(refreshed)

    @staticmethod
    async def update_payment(
        db: AsyncSession, current_user: User, payment_id: str, req: PaymentUpdateRequest
    ) -> PaymentResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        payment = await PaymentRepository.get_payment_by_id(db, payment_id, current_user.tenant_id)
        if not payment:
            raise ResourceNotFoundException(f"Payment ID '{payment_id}' not found")

        before_state = {
            "amount": payment.amount,
            "payment_status": payment.payment_status,
            "payment_method": payment.payment_method,
        }

        for field in ["amount", "payment_date", "payment_method", "payment_status", "remarks"]:
            val = getattr(req, field, None)
            if val is not None:
                setattr(payment, field, val)

        after_state = {
            "amount": payment.amount,
            "payment_status": payment.payment_status,
            "payment_method": payment.payment_method,
        }

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PAYMENT_UPDATE",
            target_entity="payments",
            target_id=payment_id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()

        # NOTE: even a status transition to SUCCESS here deliberately does NOT
        # create a passbook entry. See create_passbook_entry_for_payment below.

        refreshed = await PaymentRepository.get_payment_by_id(db, payment_id, current_user.tenant_id)
        return _to_admin_response(refreshed)

    # ─── Customer (read-only) ───

    @staticmethod
    async def get_customer_payments(db: AsyncSession, current_user: User) -> List[CustomerPaymentResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        payments = await PaymentRepository.get_payments_by_customer(db, current_user.tenant_id, current_user.id)
        return [_to_customer_response(p) for p in payments]

    @staticmethod
    async def get_customer_payment_by_id(
        db: AsyncSession, current_user: User, payment_id: str
    ) -> CustomerPaymentResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        payment = await PaymentRepository.get_payment_by_id_for_customer(
            db, payment_id, current_user.tenant_id, current_user.id
        )
        if not payment:
            raise ResourceNotFoundException(f"Payment ID '{payment_id}' not found")
        return _to_customer_response(payment)

    # ─── Passbook integration extension point (NOT called anywhere) ───

    @staticmethod
    async def create_passbook_entry_for_payment(db: AsyncSession, payment: Payment) -> None:
        """
        Documented integration point for the future Payments↔Passbook workflow.

        Once the payment workflow is finalized (gold-rate-at-payment-time source,
        installment sequencing, GST/fee decisions), a SUCCESSFUL payment should be
        able to create exactly one PassbookEntry and link it back via
        Payment.passbook_entry_id. That linkage, the entry_number sequencing, and
        the gold_rate/gold_weight calculation are all undecided — deliberately not
        implemented here per Module 10 scope ("do NOT automatically create passbook
        entries in this module").

        This method is intentionally not called by create_manual_payment or
        update_payment above. Wiring it in is future work, not a bug.
        """
        raise NotImplementedError(
            "Passbook entry creation from a payment is not implemented yet. "
            "This is a documented extension point for a future module."
        )
