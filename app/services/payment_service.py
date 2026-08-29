import uuid
from datetime import date
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.payment import Payment, STATUS_SUCCESS
from app.models.passbook import PassbookEntry
from app.repositories.payment_repository import PaymentRepository
from app.models.enrollment import CONTRIBUTABLE_STATUSES
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.passbook_repository import PassbookRepository
from app.repositories.goldrate_repository import GoldRateRepository
from app.repositories.audit_repository import AuditRepository
from app.services.enrollment_service import _add_months, resolve_enrollment_terms
from app.exceptions.base import (
    ResourceNotFoundException, ForbiddenException, ConflictException, ValidationException,
)
from app.schemas.payment import PaymentManualCreateRequest, PaymentUpdateRequest, PaymentResponse, CustomerPaymentResponse


def _generate_payment_reference() -> str:
    return f"PAY-{date.today():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _round2(v: float) -> float:
    return round(v + 1e-9, 2)


def _round3(v: float) -> float:
    """Gold weight in grams, 3-decimal convention used across the product
    (ai_analyst_service, passbook frontend). No arbitrary precision introduced."""
    return round(v, 3)


def _derive_months(amount: float, eff_monthly: float) -> int:
    """Whole-month installments a contribution covers, DERIVED from the amount and
    the enrollment's own monthly amount — never taken from the client.

    Amount-first business rule: a scheme contribution must equal
    monthly_amount x N whole months. A non-multiple (e.g. 1500 on a 1000/month
    enrollment) is REJECTED, never silently under-credited as 1 month — that
    mismatch was the root cause of months_paid disagreeing with the ledger. The
    per-month capacity check in _apply_successful_contribution then bounds N to
    the remaining duration, which — because amount == monthly x N — is exactly
    the base-maturity (monthly x duration) rupee cap, so contributions can never
    exceed the enrollment's base maturity."""
    if not eff_monthly or eff_monthly <= 0:
        raise ValidationException(
            "This enrollment has no monthly amount configured; a scheme "
            "contribution cannot be recorded against it."
        )
    months = int(round(amount / eff_monthly))
    if months < 1 or abs(amount - eff_monthly * months) > 0.005:
        raise ValidationException(
            f"Contribution must be a whole-month multiple of the {eff_monthly:g} "
            f"monthly amount (e.g. {eff_monthly:g}, {eff_monthly * 2:g}, "
            f"{eff_monthly * 3:g}); got {amount:g}."
        )
    return months


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
    async def _apply_successful_contribution(
        db: AsyncSession,
        current_user: User,
        enrollment,
        eff_duration: int,
        months: int,
        payment: Payment,
    ) -> str:
        """Advance enrollment coverage and create the single PassbookEntry for a
        SUCCESSFUL scheme contribution, inside the caller's already-row-locked
        transaction. Returns the new passbook entry id.

        The ONE contribution-advance implementation, shared by
        create_manual_payment (created SUCCESS) and update_payment
        (PENDING -> SUCCESS). Caller guarantees: enrollment row-locked and
        CONTRIBUTABLE, amount already validated, Payment row already created, and
        the payment not already linked to an entry (no double processing)."""
        tenant_id = enrollment.tenant_id

        # Capacity: never advance beyond the scheme's duration.
        if enrollment.months_paid + months > eff_duration:
            remaining = max(0, eff_duration - enrollment.months_paid)
            raise ConflictException(
                f"Contribution of {months} month(s) exceeds the scheme's remaining "
                f"coverage ({remaining} of {eff_duration} months left)."
            )

        # Window this transaction pays for, from the enrollment's current coverage.
        payment.period_start = _add_months(enrollment.joined_date, enrollment.months_paid)
        payment.period_end = _add_months(enrollment.joined_date, enrollment.months_paid + months)

        enrollment.months_paid += months
        enrollment.next_due_date = (
            _add_months(enrollment.joined_date, enrollment.months_paid)
            if enrollment.months_paid < eff_duration else None
        )

        # Gold rate: existing GoldRate source at the payment date, else the most
        # recent rate on/before it — never a future rate, never fabricated.
        # rate_24k is INR per gram, so gold_weight = amount / rate.
        rate_row = await GoldRateRepository.get_rate_for_date(
            db, tenant_id, payment.payment_date
        )
        if rate_row is None:
            rate_row = await GoldRateRepository.get_rate_on_or_before(
                db, tenant_id, payment.payment_date
            )
        if rate_row is None:
            raise ValidationException(
                "No gold rate has been published for this store. Set today's gold "
                "rate before recording a scheme contribution."
            )
        gold_rate = float(rate_row.rate_24k)
        gold_weight = _round3(payment.amount / gold_rate)

        entry_number = await PassbookRepository.next_entry_number(
            db, enrollment.id, tenant_id
        )
        description = (
            "Scheme contribution"
            if months == 1
            else f"Advance contribution ({months} months)"
        )
        entry = PassbookEntry(
            id=f"pbk_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            enrollment_id=enrollment.id,
            entry_number=entry_number,
            entry_date=payment.payment_date,
            description=description,
            amount=payment.amount,
            gold_rate=gold_rate,
            gold_weight=gold_weight,
            running_installment_count=enrollment.months_paid,
            remarks=payment.remarks,
            created_by=current_user.id,
        )
        await PassbookRepository.create_entry(db, entry)
        payment.passbook_entry_id = entry.id
        return entry.id

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
        # The Admin enters the visible enrollment number (ENR-...); older callers
        # may pass the internal id (enr_...). Resolve either, tenant-scoped.
        enrollment = await EnrollmentRepository.get_enrollment_by_id_or_number_for_update(
            db, req.enrollment_id, tenant_id
        )
        if not enrollment:
            raise ResourceNotFoundException(f"Enrollment '{req.enrollment_id}' not found")
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
        # Resolve the enrollment's OWN terms — its selected-tier snapshot when it
        # has one, else the scheme base. A tier edit must never change the monthly
        # amount or duration an already-enrolled customer pays against.
        eff_monthly, eff_duration = resolve_enrollment_terms(enrollment, scheme)
        duration = eff_duration

        # Amount-first rule: the installments this payment covers are DERIVED from
        # the amount and the enrollment's monthly amount, never taken from the
        # client. A non-multiple is rejected here (backend is authoritative);
        # req.months_covered is ignored. Capacity/base-maturity is enforced by
        # _apply_successful_contribution using this derived count.
        months = _derive_months(req.amount, eff_monthly)

        # Coverage only advances for a SUCCESSFUL contribution. A failed/pending
        # payment creates no coverage and no passbook entry.
        will_advance = status == STATUS_SUCCESS

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
            period_start=None,
            period_end=None,
            gateway_name=None,
            gateway_transaction_id=None,
            remarks=req.remarks,
            created_by=current_user.id,
        )
        await PaymentRepository.create_payment(db, payment)

        # One SUCCESSFUL contribution => exactly one PassbookEntry + coverage
        # advance, in this same row-locked transaction (shared helper). Capacity,
        # period, gold rate and entry-number all handled there. A retry returns
        # early on the idempotency check above, so no duplicate payment/entry.
        passbook_entry_id = None
        if will_advance:
            passbook_entry_id = await PaymentService._apply_successful_contribution(
                db, current_user, enrollment, duration, months, payment
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
                "passbook_entry_id": passbook_entry_id,
            },
        )

        # Single commit: payment row + coverage advance + passbook entry land
        # together, or none of them.
        await db.commit()

        refreshed = await PaymentRepository.get_payment_by_id(db, payment_id, tenant_id)
        return _to_admin_response(refreshed)

    @staticmethod
    async def update_payment(
        db: AsyncSession, current_user: User, payment_id: str, req: PaymentUpdateRequest
    ) -> PaymentResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        tenant_id = current_user.tenant_id
        payment = await PaymentRepository.get_payment_by_id(db, payment_id, tenant_id)
        if not payment:
            raise ResourceNotFoundException(f"Payment ID '{payment_id}' not found")

        was_success = payment.payment_status == STATUS_SUCCESS

        before_state = {
            "amount": payment.amount,
            "payment_status": payment.payment_status,
            "payment_method": payment.payment_method,
        }

        for field in ["amount", "payment_date", "payment_method", "payment_status", "remarks"]:
            val = getattr(req, field, None)
            if val is not None:
                setattr(payment, field, val)

        # A PENDING/other -> SUCCESS transition (e.g. a cheque clearing) is a real
        # contribution and must advance coverage and create the passbook entry,
        # exactly like a payment created SUCCESS — through the SAME shared helper.
        # Guarded so it happens at most once:
        #   - only when the status actually crosses INTO success (not was_success),
        #   - and only when this payment has no passbook entry yet.
        # A payment already SUCCESS is left untouched (no backfill of legacy rows).
        passbook_entry_id = payment.passbook_entry_id
        now_success = payment.payment_status == STATUS_SUCCESS
        if now_success and not was_success and payment.passbook_entry_id is None:
            # Row-lock the enrollment so a concurrent contribution/transition on
            # the same enrollment serialises and reads a fresh months_paid.
            enrollment = await EnrollmentRepository.get_enrollment_by_id_for_update(
                db, payment.enrollment_id, tenant_id
            )
            if not enrollment:
                raise ResourceNotFoundException(
                    f"Enrollment ID '{payment.enrollment_id}' not found"
                )
            # Re-read the live link UNDER the lock: if a concurrent transition
            # already created the entry for this payment, do not create a second
            # one or advance twice. (autoflush persists our own pending changes
            # into this uncommitted transaction only.)
            live_link = (await db.execute(
                select(Payment.passbook_entry_id).where(
                    Payment.id == payment_id, Payment.tenant_id == tenant_id
                )
            )).scalar_one()
            if live_link is not None:
                passbook_entry_id = live_link
            else:
                if enrollment.status not in CONTRIBUTABLE_STATUSES:
                    raise ConflictException(
                        f"Enrollment {enrollment.enrollment_number} is "
                        f"{enrollment.status.lower()} and no longer accepts contributions."
                    )
                from app.repositories.scheme_repository import SchemeRepository
                scheme = await SchemeRepository.get_scheme_by_id(
                    db, enrollment.scheme_id, tenant_id
                )
                if scheme is None:
                    raise ResourceNotFoundException(
                        f"Scheme ID '{enrollment.scheme_id}' not found"
                    )
                eff_monthly, eff_duration = resolve_enrollment_terms(enrollment, scheme)
                # Same amount-first rule as create: installments derived from the
                # (possibly just-updated) amount, non-multiple rejected. Persist
                # the corrected months_covered on the payment.
                months = _derive_months(payment.amount, eff_monthly)
                payment.months_covered = months
                passbook_entry_id = await PaymentService._apply_successful_contribution(
                    db, current_user, enrollment, eff_duration, months, payment
                )

        after_state = {
            "amount": payment.amount,
            "payment_status": payment.payment_status,
            "payment_method": payment.payment_method,
            "passbook_entry_id": passbook_entry_id,
        }

        await AuditRepository.create_log(
            db,
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PAYMENT_UPDATE",
            target_entity="payments",
            target_id=payment_id,
            before_state=before_state,
            after_state=after_state,
        )

        # Single commit: field edits + (if it transitioned to SUCCESS) coverage
        # advance + passbook entry land together, or none of them.
        await db.commit()

        refreshed = await PaymentRepository.get_payment_by_id(db, payment_id, tenant_id)
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
