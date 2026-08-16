import uuid
from datetime import date, datetime, timezone
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SALE_STATUS_COMPLETED
from app.models.auth import User
from app.models.billing import SalePayment, PAYMENT_SOURCE_SCHEME_REDEMPTION
from app.models.enrollment import (
    SchemeEnrollment,
    SchemeRedemption,
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_CLOSED,
    STATUS_REDEEMED,
    CONTRIBUTABLE_STATUSES,
    REDEEMABLE_STATUSES,
)
from app.repositories.enrollment_repository import EnrollmentRepository, SchemeRedemptionRepository
from app.repositories.billing_repository import SaleRepository, SalePaymentRepository
from app.repositories.scheme_repository import SchemeRepository
from app.repositories.audit_repository import AuditRepository
from app.services.billing_service import _derive_payment_status
from app.services.goldrate_service import IST
from app.exceptions.base import ResourceNotFoundException, ConflictException, ForbiddenException, ValidationException
from app.schemas.enrollment import (
    EnrollmentCreateRequest,
    EnrollmentResponse,
    CustomerEnrollmentResponse,
    EnrollmentBalanceResponse,
    EnrollmentCloseRequest,
    SchemeRedeemRequest,
    SchemeRedemptionResponse,
)


def _add_months(start: date, months: int) -> date:
    """Add N months to a date, clamping the day for shorter target months (no external deps)."""
    total_month_index = start.month - 1 + months
    year = start.year + total_month_index // 12
    month = total_month_index % 12 + 1
    day = min(start.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def _generate_enrollment_number() -> str:
    return f"ENR-{date.today():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _to_admin_response(enrollment: SchemeEnrollment) -> EnrollmentResponse:
    return EnrollmentResponse(
        id=enrollment.id,
        tenant_id=enrollment.tenant_id,
        customer_id=enrollment.customer_id,
        customer_name=enrollment.customer.name,
        scheme_id=enrollment.scheme_id,
        scheme_name=enrollment.scheme.name,
        enrollment_number=enrollment.enrollment_number,
        joined_date=enrollment.joined_date,
        status=enrollment.status,
        maturity_date=enrollment.maturity_date,
        created_at=enrollment.created_at,
        updated_at=enrollment.updated_at,
    )


def _to_customer_response(enrollment: SchemeEnrollment) -> CustomerEnrollmentResponse:
    return CustomerEnrollmentResponse(
        id=enrollment.id,
        scheme_id=enrollment.scheme_id,
        scheme_name=enrollment.scheme.name,
        enrollment_number=enrollment.enrollment_number,
        joined_date=enrollment.joined_date,
        status=enrollment.status,
        maturity_date=enrollment.maturity_date,
    )


class EnrollmentService:
    # ─── Admin (read-only) ───

    @staticmethod
    async def get_enrollments(db: AsyncSession, current_user: User) -> List[EnrollmentResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        enrollments = await EnrollmentRepository.get_enrollments_by_tenant(db, current_user.tenant_id)
        return [_to_admin_response(e) for e in enrollments]

    @staticmethod
    async def get_enrollment_by_id(
        db: AsyncSession, current_user: User, enrollment_id: str
    ) -> EnrollmentResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        enrollment = await EnrollmentRepository.get_enrollment_by_id(db, enrollment_id, current_user.tenant_id)
        if not enrollment:
            raise ResourceNotFoundException(f"Enrollment ID '{enrollment_id}' not found")
        return _to_admin_response(enrollment)

    # ─── Customer ───

    @staticmethod
    async def create_enrollment(
        db: AsyncSession, current_user: User, req: EnrollmentCreateRequest
    ) -> CustomerEnrollmentResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        scheme = await SchemeRepository.get_scheme_by_id(db, req.scheme_id, current_user.tenant_id)
        if not scheme:
            raise ResourceNotFoundException(f"Scheme ID '{req.scheme_id}' not found")

        if not scheme.is_active:
            raise ValidationException("This scheme is not currently active and cannot accept new enrollments")

        existing = await EnrollmentRepository.get_active_enrollment_for_scheme(
            db, current_user.tenant_id, current_user.id, req.scheme_id
        )
        if existing:
            raise ConflictException("You already have an active enrollment in this scheme")

        today = date.today()
        enrollment = SchemeEnrollment(
            id=f"enr_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            customer_id=current_user.id,
            scheme_id=scheme.id,
            enrollment_number=_generate_enrollment_number(),
            joined_date=today,
            status=STATUS_ACTIVE,
            maturity_date=_add_months(today, scheme.duration_months),
        )
        await EnrollmentRepository.create_enrollment(db, enrollment)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="ENROLLMENT_CREATE",
            target_entity="scheme_enrollments",
            target_id=enrollment.id,
            before_state=None,
            after_state={"scheme_id": scheme.id, "enrollment_number": enrollment.enrollment_number},
        )

        await db.commit()

        # Re-fetch with relationships eagerly loaded for the response (avoids lazy-load in async context)
        created = await EnrollmentRepository.get_enrollment_by_id_for_customer(
            db, enrollment.id, current_user.tenant_id, current_user.id
        )
        return _to_customer_response(created)

    @staticmethod
    async def get_customer_enrollments(
        db: AsyncSession, current_user: User
    ) -> List[CustomerEnrollmentResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        enrollments = await EnrollmentRepository.get_enrollments_by_customer(
            db, current_user.tenant_id, current_user.id
        )
        return [_to_customer_response(e) for e in enrollments]

    @staticmethod
    async def get_customer_enrollment_by_id(
        db: AsyncSession, current_user: User, enrollment_id: str
    ) -> CustomerEnrollmentResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        enrollment = await EnrollmentRepository.get_enrollment_by_id_for_customer(
            db, enrollment_id, current_user.tenant_id, current_user.id
        )
        if not enrollment:
            raise ResourceNotFoundException(f"Enrollment ID '{enrollment_id}' not found")
        return _to_customer_response(enrollment)


def _round2(value: float) -> float:
    return round(value, 2)


# Money tolerance, same convention as the billing ledger: amounts are stored as
# Float and rounded to paise, so anything within half a paise counts as equal.
_MONEY_EPSILON = 0.005


class SchemeBalanceService:
    """Scheme credit: closure, balance, and redemption against a jewellery sale.

    The available balance is ALWAYS derived —
        SUM(successful scheme contributions) - SUM(redemptions)
    — never read from a cached column, so several partial redemptions against
    one enrollment cannot drift. No bonus is added: Scheme.bonus_description is
    free text and the product has no numeric bonus rule, so applying one here
    would fabricate money.

    Money movement reuses the existing sale_payments ledger with
    source=SCHEME_REDEMPTION and the funding enrollment_id. There is no second
    payment system, and because that source is excluded from cash reporting a
    redemption can never be counted as counter cash.
    """

    @staticmethod
    async def _actor_names(db: AsyncSession, ids: list) -> dict:
        wanted = {i for i in ids if i}
        if not wanted:
            return {}
        rows = (await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))).all()
        return {r[0]: r[1] for r in rows}

    @staticmethod
    async def _balance_of(db: AsyncSession, enrollment: SchemeEnrollment) -> tuple:
        """(total_paid, total_redeemed, available) — all derived from ledgers."""
        total_paid = _round2(
            await SchemeRedemptionRepository.sum_successful_contributions(
                db, enrollment.id, enrollment.tenant_id
            )
        )
        total_redeemed = _round2(
            await SchemeRedemptionRepository.sum_for_enrollment(
                db, enrollment.id, enrollment.tenant_id
            )
        )
        return total_paid, total_redeemed, _round2(max(0.0, total_paid - total_redeemed))

    @staticmethod
    async def get_balance(
        db: AsyncSession, current_user: User, enrollment_id: str
    ) -> EnrollmentBalanceResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        enrollment = await EnrollmentRepository.get_enrollment_by_id(
            db, enrollment_id, current_user.tenant_id
        )
        if not enrollment:
            raise ResourceNotFoundException(f"Enrollment ID '{enrollment_id}' not found")

        total_paid, total_redeemed, available = await SchemeBalanceService._balance_of(db, enrollment)
        payment_count = await SchemeRedemptionRepository.count_successful_contributions(
            db, enrollment.id, enrollment.tenant_id
        )
        redemptions = await SchemeRedemptionRepository.list_for_enrollment(
            db, enrollment.id, enrollment.tenant_id
        )
        names = await SchemeBalanceService._actor_names(
            db, [enrollment.closed_by] + [r.recorded_by for r in redemptions]
        )

        return EnrollmentBalanceResponse(
            enrollment_id=enrollment.id,
            enrollment_number=enrollment.enrollment_number,
            customer_id=enrollment.customer_id,
            customer_name=enrollment.customer.name,
            scheme_name=enrollment.scheme.name,
            monthly_amount=enrollment.scheme.monthly_amount,
            duration_months=enrollment.scheme.duration_months,
            successful_payment_count=payment_count,
            total_paid=total_paid,
            total_redeemed=total_redeemed,
            available_balance=available,
            status=enrollment.status,
            joined_date=enrollment.joined_date,
            maturity_date=enrollment.maturity_date,
            closed_at=enrollment.closed_at,
            closed_by=enrollment.closed_by,
            closed_by_name=names.get(enrollment.closed_by) if enrollment.closed_by else None,
            closure_reason=enrollment.closure_reason,
            can_contribute=enrollment.status in CONTRIBUTABLE_STATUSES,
            can_redeem=enrollment.status in REDEEMABLE_STATUSES and available > _MONEY_EPSILON,
            redemptions=[
                SchemeRedemptionResponse(
                    id=r.id,
                    enrollment_id=r.enrollment_id,
                    customer_id=r.customer_id,
                    sale_id=r.sale_id,
                    invoice_number=r.invoice_number,
                    amount=_round2(r.amount),
                    redeemed_at=r.redeemed_at,
                    recorded_by=r.recorded_by,
                    recorded_by_name=names.get(r.recorded_by),
                )
                for r in redemptions
            ],
        )

    @staticmethod
    async def close_enrollment(
        db: AsyncSession, current_user: User, enrollment_id: str, req: EnrollmentCloseRequest
    ) -> EnrollmentBalanceResponse:
        """Stop future contributions, keep the money.

        Nothing is deleted and no payment is rewritten: the enrollment and its
        whole contribution history stay readable, and the balance already paid in
        remains redeemable customer credit. Closing never refunds and never
        forfeits.
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        enrollment = await EnrollmentRepository.get_enrollment_by_id_for_update(
            db, enrollment_id, current_user.tenant_id
        )
        if not enrollment:
            raise ResourceNotFoundException(f"Enrollment ID '{enrollment_id}' not found")
        if enrollment.status in (STATUS_CLOSED, STATUS_REDEEMED, STATUS_CANCELLED):
            raise ConflictException(
                f"Enrollment {enrollment.enrollment_number} is already {enrollment.status.lower()}."
            )

        total_paid, total_redeemed, available = await SchemeBalanceService._balance_of(db, enrollment)
        before_status = enrollment.status

        enrollment.status = STATUS_CLOSED
        enrollment.closed_at = datetime.now(timezone.utc)
        enrollment.closed_by = current_user.id
        enrollment.closure_reason = req.reason

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SCHEME_ENROLLMENT_CLOSE",
            target_entity="scheme_enrollments",
            target_id=enrollment.id,
            before_state={"status": before_status},
            after_state={
                "enrollment_number": enrollment.enrollment_number,
                "status": enrollment.status,
                "closure_reason": req.reason,
                "total_paid": total_paid,
                "total_redeemed": total_redeemed,
                "available_balance": available,
                "closed_at": enrollment.closed_at.isoformat(),
                "closed_by": current_user.id,
            },
        )

        await db.commit()
        return await SchemeBalanceService.get_balance(db, current_user, enrollment_id)

    @staticmethod
    async def redeem_against_sale(
        db: AsyncSession, current_user: User, enrollment_id: str, req: SchemeRedeemRequest
    ) -> EnrollmentBalanceResponse:
        """Apply scheme credit to an existing jewellery invoice, atomically.

        Ordering is deliberate:
          1. lock the enrollment (tenant-scoped) for the rest of the transaction
          2. derive the available balance from both ledgers, not a cache
          3. lock the sale and refuse a reversed one
          4. reject an amount above the balance OR above the sale's outstanding
          5. write the immutable SchemeRedemption row
          6. append the SCHEME_REDEMPTION row to the existing sale_payments
             ledger, carrying enrollment_id
          7. refresh the sale's derived amount_paid/payment_status
          8. flip the enrollment to REDEEMED once the balance is exhausted
          9. audit, then commit ONCE

        Step 1 is what stops two Admins redeeming the same enrollment against two
        invoices simultaneously and together spending more credit than the
        customer ever paid in. Step 3's lock does the same on the invoice side.
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        enrollment = await EnrollmentRepository.get_enrollment_by_id_for_update(
            db, enrollment_id, current_user.tenant_id
        )
        if not enrollment:
            raise ResourceNotFoundException(f"Enrollment ID '{enrollment_id}' not found")
        if enrollment.status not in REDEEMABLE_STATUSES:
            raise ConflictException(
                f"Enrollment {enrollment.enrollment_number} is {enrollment.status.lower()} and its "
                f"balance can no longer be redeemed."
            )

        total_paid, total_redeemed, available = await SchemeBalanceService._balance_of(db, enrollment)
        if available <= _MONEY_EPSILON:
            raise ConflictException(
                f"Enrollment {enrollment.enrollment_number} has no scheme balance left to redeem."
            )

        # Tenant-scoped: an enrollment from one tenant can never settle another
        # tenant's invoice, because both lookups are scoped to the caller's.
        sale = await SaleRepository.get_by_id_for_update(db, req.sale_id, current_user.tenant_id)
        if not sale:
            raise ResourceNotFoundException(f"Sale '{req.sale_id}' not found")
        # Customer ownership: a customer's scheme balance may only settle that
        # same customer's invoice. Tenant is already enforced by the scoped
        # lookup above; this stops one customer's credit paying another's bill
        # inside the same tenant. A sale with no customer_id can never be
        # matched to an enrollment's customer, so it is rejected too.
        if sale.customer_id != enrollment.customer_id:
            raise ConflictException(
                f"Invoice {sale.invoice_number} belongs to a different customer and cannot be "
                f"settled with this scheme balance."
            )
        if (sale.sale_status or SALE_STATUS_COMPLETED) != SALE_STATUS_COMPLETED:
            raise ConflictException(
                f"Invoice {sale.invoice_number} is {sale.sale_status.lower()} — scheme credit cannot "
                f"be applied to a reversed sale."
            )

        amount = _round2(req.amount)
        if amount <= 0:
            raise ValidationException("Redemption amount must be greater than zero")
        if amount > available + _MONEY_EPSILON:
            raise ValidationException(
                f"Redemption of {amount} exceeds the {available} scheme balance available on "
                f"enrollment {enrollment.enrollment_number}."
            )

        already_paid = _round2(
            await SalePaymentRepository.sum_for_sale(db, sale.id, current_user.tenant_id)
        )
        outstanding = _round2(sale.final_amount - already_paid)
        if outstanding <= _MONEY_EPSILON:
            raise ConflictException(
                f"Invoice {sale.invoice_number} is already fully settled — nothing is outstanding."
            )
        if amount > outstanding + _MONEY_EPSILON:
            raise ValidationException(
                f"Redemption of {amount} exceeds the outstanding {outstanding} on invoice "
                f"{sale.invoice_number}. Apply {outstanding} or less; the rest of the scheme "
                f"balance stays available for a future purchase."
            )

        now = datetime.now(timezone.utc)

        redemption = SchemeRedemption(
            id=f"srd_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            enrollment_id=enrollment.id,
            customer_id=enrollment.customer_id,
            sale_id=sale.id,
            invoice_number=sale.invoice_number,
            amount=amount,
            redeemed_at=now,
            recorded_by=current_user.id,
        )
        await SchemeRedemptionRepository.create(db, redemption)

        # Settles the invoice like any other collection, but source=SCHEME_REDEMPTION
        # keeps it out of cash reporting: this is the customer spending money the
        # store already received months ago, not new cash at the counter.
        ledger_row = SalePayment(
            id=f"sp_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            sale_id=sale.id,
            amount=amount,
            payment_date=datetime.now(IST).date(),
            payment_method="OTHER",
            source=PAYMENT_SOURCE_SCHEME_REDEMPTION,
            reference_no=enrollment.enrollment_number,
            remarks=f"Scheme redemption from enrollment {enrollment.enrollment_number}",
            enrollment_id=enrollment.id,
            recorded_by=current_user.id,
        )
        await SalePaymentRepository.create(db, ledger_row)

        new_paid = _round2(already_paid + amount)
        sale.amount_paid = new_paid
        sale.payment_status = _derive_payment_status(sale.final_amount, new_paid)

        new_redeemed = _round2(total_redeemed + amount)
        remaining = _round2(max(0.0, total_paid - new_redeemed))
        before_status = enrollment.status
        if remaining <= _MONEY_EPSILON:
            enrollment.status = STATUS_REDEEMED

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SCHEME_REDEMPTION_APPLY",
            target_entity="scheme_redemptions",
            target_id=redemption.id,
            before_state={
                "enrollment_status": before_status,
                "available_balance": available,
                "sale_amount_paid": already_paid,
                "sale_payment_status": sale.payment_status,
            },
            after_state={
                "enrollment_id": enrollment.id,
                "enrollment_number": enrollment.enrollment_number,
                "customer_id": enrollment.customer_id,
                "sale_id": sale.id,
                "invoice_number": sale.invoice_number,
                "amount": amount,
                "total_paid": total_paid,
                "total_redeemed": new_redeemed,
                "available_balance": remaining,
                "enrollment_status": enrollment.status,
                "sale_amount_paid": new_paid,
                "sale_payment_status": sale.payment_status,
                "redeemed_at": now.isoformat(),
                "recorded_by": current_user.id,
            },
        )

        await db.commit()
        return await SchemeBalanceService.get_balance(db, current_user, enrollment_id)
