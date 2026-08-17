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
from app.services.enrollment_service import _add_months
from app.exceptions.base import (
    ResourceNotFoundException, ForbiddenException, ConflictException, ValidationException,
)
from app.schemas.payment import PaymentManualCreateRequest, PaymentUpdateRequest, PaymentResponse, CustomerPaymentResponse


def _generate_payment_reference() -> str:
    return f"PAY-{date.today():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _round2(v: float) -> float:
    return round(v + 1e-9, 2)


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
        months_covered=payment.months_covered,
        period_start=payment.period_start,
        period_end=payment.period_end,
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
        months_covered=payment.months_covered,
        period_start=payment.period_start,
        period_end=payment.period_end,
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
        """Admin records a scheme contribution collected outside the app
        (cash/bank transfer/cheque/etc.).

        Phase 3: a single call may cover 1, 3 or 6 monthly installments in ONE
        real financial transaction (months_covered). It is recorded as exactly
        one Payment row — never N fabricated monthly rows — and, when SUCCESSFUL,
        advances the enrollment's coverage (months_paid) and next_due_date inside
        one row-locked transaction, so:
          - concurrent contributions serialise (no double-advance from stale state),
          - a failed/pending payment changes neither balance nor coverage,
          - a retry carrying the same idempotency_key returns the existing row.
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        tenant_id = current_user.tenant_id

        months = req.months_covered or 1
        status = req.payment_status or STATUS_SUCCESS

        # Idempotency: a caller-supplied key doubles as the payment_reference,
        # which is UNIQUE per tenant. Check first so a retry is a no-op read;
        # the unique constraint is the concurrency backstop if two retries race.
        if req.idempotency_key:
            existing = await PaymentRepository.get_payment_by_reference(
                db, tenant_id, req.idempotency_key
            )
            if existing:
                return _to_admin_response(existing)

        # Row-lock the enrollment so a concurrent contribution to the same
        # enrollment serialises here and reads a fresh months_paid.
        enrollment = await EnrollmentRepository.get_enrollment_by_id_for_update(
            db, req.enrollment_id, tenant_id
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

        # Fetch scheme for duration + monthly amount. The row-locked enrollment
        # fetch does NOT eager-load relations, so never touch enrollment.scheme
        # here (lazy access would raise in async) — load it explicitly.
        from app.repositories.scheme_repository import SchemeRepository
        scheme = await SchemeRepository.get_scheme_by_id(db, enrollment.scheme_id, tenant_id)
        if scheme is None:
            raise ResourceNotFoundException(f"Scheme ID '{enrollment.scheme_id}' not found")
        duration = scheme.duration_months

        # Advance contributions must pay the exact monthly amount × months so
        # coverage and rupees stay reconciled. A plain 1-month contribution keeps
        # its historical freedom (partial monthly amounts still allowed).
        if months > 1:
            expected = _round2(scheme.monthly_amount * months)
            if _round2(req.amount) != expected:
                raise ValidationException(
                    f"A {months}-month advance must be exactly {expected} "
                    f"({scheme.monthly_amount} × {months}); got {req.amount}"
                )

        # Coverage only advances for a SUCCESSFUL contribution. Capacity is
        # checked against the scheme duration only when it will actually advance.
        will_advance = status == STATUS_SUCCESS
        if will_advance and enrollment.months_paid + months > duration:
            remaining = max(0, duration - enrollment.months_paid)
            raise ConflictException(
                f"Contribution of {months} month(s) exceeds the scheme's remaining "
                f"coverage ({remaining} of {duration} months left)."
            )

        # Window this transaction pays for, from the enrollment's current coverage.
        period_start = _add_months(enrollment.joined_date, enrollment.months_paid)
        period_end = _add_months(enrollment.joined_date, enrollment.months_paid + months)

        payment_id = f"pay_{uuid.uuid4().hex[:12]}"
        payment = Payment(
            id=payment_id,
            tenant_id=tenant_id,
            enrollment_id=enrollment.id,
            passbook_entry_id=None,
            payment_reference=req.idempotency_key or _generate_payment_reference(),
            amount=req.amount,
            payment_date=req.payment_date or date.today(),
            payment_method=req.payment_method,
            payment_status=status,
            months_covered=months,
            period_start=period_start if will_advance else None,
            period_end=period_end if will_advance else None,
            gateway_name=None,
            gateway_transaction_id=None,
            remarks=req.remarks,
            created_by=current_user.id,
        )
        await PaymentRepository.create_payment(db, payment)

        if will_advance:
            enrollment.months_paid += months
            enrollment.next_due_date = (
                _add_months(enrollment.joined_date, enrollment.months_paid)
                if enrollment.months_paid < duration else None
            )

        await AuditRepository.create_log(
            db,
            tenant_id=tenant_id,
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
                "payment_status": status,
                "months_covered": months,
                "next_due_date": str(enrollment.next_due_date) if will_advance else None,
            },
        )

        # Single commit: payment row + coverage advance land together, or neither.
        await db.commit()

        # NOTE: a successful contribution deliberately does NOT create a passbook
        # entry here — see PaymentService.create_passbook_entry_for_payment.

        refreshed = await PaymentRepository.get_payment_by_id(db, payment_id, tenant_id)
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
