import uuid
from datetime import date, datetime, timezone
from typing import List, Optional
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
    MultiSchemeRedeemRequest,
    MultiSchemeRedeemResponse,
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


def resolve_enrollment_terms(enrollment: SchemeEnrollment, scheme) -> tuple:
    """Single source of truth for an enrollment's EFFECTIVE terms.

    Returns (monthly_amount, duration_months): the snapshot frozen at enrollment
    time when the enrollment selected a tier, else the scheme's current base
    terms for legacy enrollments that predate tiers. Every calculation that
    needs an enrollment's amount/duration — maturity, advance capacity, passbook,
    balance — must go through here so tier edits apply ONLY to new enrollments.

    Only reads plain columns on `enrollment` (selected_*), so it is safe with a
    row-locked enrollment that has no relations eager-loaded, as long as the
    caller passes the scheme explicitly.
    """
    monthly = enrollment.selected_monthly_amount
    duration = enrollment.selected_duration_months
    if monthly is None or duration is None:
        return scheme.monthly_amount, scheme.duration_months
    return monthly, duration


def maturity_amount(monthly: float, duration: int) -> float:
    """Maturity value = monthly installment x number of months. No bonus,
    interest or appreciation — the product has no such rule."""
    return round((monthly or 0) * (duration or 0), 2)


def _to_admin_response(enrollment: SchemeEnrollment) -> EnrollmentResponse:
    monthly, duration = resolve_enrollment_terms(enrollment, enrollment.scheme)
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
        months_paid=enrollment.months_paid,
        next_due_date=enrollment.next_due_date,
        remarks=enrollment.remarks,
        scheme_tier_id=enrollment.scheme_tier_id,
        monthly_amount=monthly,
        duration_months=duration,
        maturity_amount=maturity_amount(monthly, duration),
        created_at=enrollment.created_at,
        updated_at=enrollment.updated_at,
    )


def _to_customer_response(enrollment: SchemeEnrollment) -> CustomerEnrollmentResponse:
    monthly, duration = resolve_enrollment_terms(enrollment, enrollment.scheme)
    return CustomerEnrollmentResponse(
        id=enrollment.id,
        scheme_id=enrollment.scheme_id,
        scheme_name=enrollment.scheme.name,
        enrollment_number=enrollment.enrollment_number,
        joined_date=enrollment.joined_date,
        status=enrollment.status,
        maturity_date=enrollment.maturity_date,
        months_paid=enrollment.months_paid,
        next_due_date=enrollment.next_due_date,
        scheme_tier_id=enrollment.scheme_tier_id,
        monthly_amount=monthly,
        duration_months=duration,
        maturity_amount=maturity_amount(monthly, duration),
    )


class EnrollmentService:
    # ─── Admin (read-only) ───

    @staticmethod
    async def get_enrollments(
        db: AsyncSession, current_user: User, customer_id: Optional[str] = None
    ) -> List[EnrollmentResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        if customer_id:
            enrollments = await EnrollmentRepository.get_enrollments_by_customer(
                db, current_user.tenant_id, customer_id
            )
        else:
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

    @staticmethod
    async def update_remarks(
        db: AsyncSession, current_user: User, enrollment_id: str, remarks
    ) -> EnrollmentResponse:
        """Edit the enrollment's free-text remark. Metadata only — no financial
        row is touched, so this stays editable regardless of contributions."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        enrollment = await EnrollmentRepository.get_enrollment_by_id(db, enrollment_id, current_user.tenant_id)
        if not enrollment:
            raise ResourceNotFoundException(f"Enrollment ID '{enrollment_id}' not found")
        before = enrollment.remarks
        enrollment.remarks = (remarks or None)
        await AuditRepository.create_log(
            db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
            actor_name=current_user.name, actor_role=current_user.role.name,
            action="ENROLLMENT_REMARKS_UPDATE", target_entity="scheme_enrollments",
            target_id=enrollment.id, before_state={"remarks": before},
            after_state={"remarks": enrollment.remarks},
        )
        await db.commit()
        refreshed = await EnrollmentRepository.get_enrollment_by_id(db, enrollment_id, current_user.tenant_id)
        return _to_admin_response(refreshed)

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

        # Tier selection. A chosen tier must belong to THIS scheme and be active;
        # its terms are snapshotted so a later tier edit never touches this
        # enrollment. No tier selected => legacy base-terms enrollment (snapshot
        # left NULL, resolves to the scheme's terms).
        selected_tier = None
        if req.scheme_tier_id:
            selected_tier = next((t for t in scheme.tiers if t.id == req.scheme_tier_id), None)
            if selected_tier is None:
                raise ResourceNotFoundException(
                    f"Scheme tier '{req.scheme_tier_id}' not found for scheme '{scheme.id}'"
                )
            if not selected_tier.is_active:
                raise ValidationException("The selected tier is not active and cannot be used for a new enrollment")

        eff_duration = selected_tier.duration_months if selected_tier else scheme.duration_months

        today = date.today()
        enrollment = SchemeEnrollment(
            id=f"enr_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            customer_id=current_user.id,
            scheme_id=scheme.id,
            enrollment_number=_generate_enrollment_number(),
            joined_date=today,
            status=STATUS_ACTIVE,
            maturity_date=_add_months(today, eff_duration),
            months_paid=0,
            next_due_date=today,  # first installment due from the join date
            scheme_tier_id=selected_tier.id if selected_tier else None,
            selected_monthly_amount=selected_tier.monthly_amount if selected_tier else None,
            selected_duration_months=selected_tier.duration_months if selected_tier else None,
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
            after_state={
                "scheme_id": scheme.id,
                "enrollment_number": enrollment.enrollment_number,
                "scheme_tier_id": enrollment.scheme_tier_id,
                "selected_monthly_amount": enrollment.selected_monthly_amount,
                "selected_duration_months": enrollment.selected_duration_months,
            },
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

        eff_monthly, eff_duration = resolve_enrollment_terms(enrollment, enrollment.scheme)

        return EnrollmentBalanceResponse(
            enrollment_id=enrollment.id,
            enrollment_number=enrollment.enrollment_number,
            customer_id=enrollment.customer_id,
            customer_name=enrollment.customer.name,
            scheme_name=enrollment.scheme.name,
            scheme_tier_id=enrollment.scheme_tier_id,
            monthly_amount=eff_monthly,
            duration_months=eff_duration,
            maturity_amount=maturity_amount(eff_monthly, eff_duration),
            months_paid=enrollment.months_paid,
            next_due_date=enrollment.next_due_date,
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


    @staticmethod
    async def redeem_multiple_against_sale(
        db: AsyncSession, current_user: User, sale_id: str, req: MultiSchemeRedeemRequest
    ) -> MultiSchemeRedeemResponse:
        """Settle ONE invoice from SEVERAL scheme balances in a single transaction.

        All-or-nothing. Every enrollment is locked and fully validated BEFORE any
        row is written, and there is exactly one commit at the end, so a failure
        on the third scheme cannot leave the first two spent. This is the reason
        the endpoint exists: chaining independent single-redemption calls from the
        frontend would leave real money half-moved when one call fails.

        Ordering is deliberate and matches redeem_against_sale (enrollments first,
        then the sale) so a concurrent single redemption and a multi redemption
        can never form a lock cycle. Enrollments are locked in sorted id order so
        two concurrent multi redemptions also acquire them in the same sequence.

          1. reject duplicate enrollments in the request
          2. lock every enrollment, sorted by id (tenant-scoped)
          3. lock the sale; refuse a reversed or already-settled invoice
          4. per enrollment: customer ownership, redeemable status, own balance
          5. reject the COMBINED amount above the invoice's outstanding
          6. only now write redemptions + SCHEME_REDEMPTION ledger rows
          7. refresh the sale's derived caches ONCE
          8. flip each exhausted enrollment to REDEEMED
          9. one audit row naming every scheme, then a single commit
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        # 1. Duplicates would double-spend one balance inside a single request,
        # and the per-enrollment balance check below would not catch it.
        seen: set = set()
        for item in req.items:
            if item.enrollment_id in seen:
                raise ValidationException(
                    f"Enrollment '{item.enrollment_id}' is listed more than once. "
                    f"Combine it into a single line."
                )
            seen.add(item.enrollment_id)

        # 2. Deterministic lock order across concurrent multi redemptions.
        ordered = sorted(req.items, key=lambda i: i.enrollment_id)

        locked: list = []
        for item in ordered:
            enrollment = await EnrollmentRepository.get_enrollment_by_id_for_update(
                db, item.enrollment_id, current_user.tenant_id
            )
            if not enrollment:
                raise ResourceNotFoundException(f"Enrollment ID '{item.enrollment_id}' not found")
            locked.append((enrollment, _round2(item.amount)))

        # 3. Sale locked after the enrollments, same direction as the single-redeem path.
        sale = await SaleRepository.get_by_id_for_update(db, sale_id, current_user.tenant_id)
        if not sale:
            raise ResourceNotFoundException(f"Sale '{sale_id}' not found")
        if (sale.sale_status or SALE_STATUS_COMPLETED) != SALE_STATUS_COMPLETED:
            raise ConflictException(
                f"Invoice {sale.invoice_number} is {sale.sale_status.lower()} — scheme credit cannot "
                f"be applied to a reversed sale."
            )

        already_paid = _round2(
            await SalePaymentRepository.sum_for_sale(db, sale.id, current_user.tenant_id)
        )
        outstanding = _round2(sale.final_amount - already_paid)
        if outstanding <= _MONEY_EPSILON:
            raise ConflictException(
                f"Invoice {sale.invoice_number} is already fully settled — nothing is outstanding."
            )

        # 4. Validate EVERY enrollment before writing anything.
        validated: list = []
        combined = 0.0
        for enrollment, amount in locked:
            if amount <= 0:
                raise ValidationException("Redemption amount must be greater than zero")
            # Customer ownership: one customer's scheme credit may never settle
            # another customer's invoice, even inside the same tenant.
            if sale.customer_id != enrollment.customer_id:
                raise ConflictException(
                    f"Invoice {sale.invoice_number} belongs to a different customer and cannot be "
                    f"settled with enrollment {enrollment.enrollment_number}."
                )
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
            if amount > available + _MONEY_EPSILON:
                raise ValidationException(
                    f"Redemption of {amount} exceeds the {available} scheme balance available on "
                    f"enrollment {enrollment.enrollment_number}."
                )
            validated.append((enrollment, amount, total_paid, total_redeemed, available))
            combined = _round2(combined + amount)

        # 5. The COMBINED amount is what the invoice can absorb. Checking only
        # per-scheme would let three valid schemes together over-settle one bill.
        if combined > outstanding + _MONEY_EPSILON:
            raise ValidationException(
                f"Combined scheme redemption of {combined} exceeds the outstanding {outstanding} on "
                f"invoice {sale.invoice_number}. Apply {outstanding} or less across the selected "
                f"schemes; the remaining scheme balances stay available for a future purchase."
            )

        # 6. Past this point every check has passed, so the writes below either
        # all land or all roll back with the single commit.
        now = datetime.now(timezone.utc)
        payment_date = datetime.now(IST).date()
        applied: list = []

        for enrollment, amount, total_paid, total_redeemed, available in validated:
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

            # One ledger row per scheme — never a merged total. The invoice must
            # keep showing which scheme funded which rupee.
            ledger_row = SalePayment(
                id=f"sp_{uuid.uuid4().hex[:12]}",
                tenant_id=current_user.tenant_id,
                sale_id=sale.id,
                amount=amount,
                payment_date=payment_date,
                payment_method="OTHER",
                source=PAYMENT_SOURCE_SCHEME_REDEMPTION,
                reference_no=enrollment.enrollment_number,
                remarks=f"Scheme redemption from enrollment {enrollment.enrollment_number}",
                enrollment_id=enrollment.id,
                recorded_by=current_user.id,
            )
            await SalePaymentRepository.create(db, ledger_row)

            new_redeemed = _round2(total_redeemed + amount)
            remaining = _round2(max(0.0, total_paid - new_redeemed))
            before_status = enrollment.status
            if remaining <= _MONEY_EPSILON:
                enrollment.status = STATUS_REDEEMED

            applied.append({
                "enrollment_id": enrollment.id,
                "enrollment_number": enrollment.enrollment_number,
                "amount": amount,
                "balance_before": available,
                "balance_after": remaining,
                "status_before": before_status,
                "status_after": enrollment.status,
            })

        # 7. Derived caches refreshed once for the whole settlement.
        new_paid = _round2(already_paid + combined)
        sale.amount_paid = new_paid
        previous_status = sale.payment_status
        sale.payment_status = _derive_payment_status(sale.final_amount, new_paid)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SCHEME_REDEMPTION_APPLY_MULTI",
            target_entity="sales",
            target_id=sale.id,
            before_state={
                "sale_amount_paid": already_paid,
                "sale_payment_status": previous_status,
                "sale_outstanding": outstanding,
            },
            after_state={
                "sale_id": sale.id,
                "invoice_number": sale.invoice_number,
                "customer_id": sale.customer_id,
                "schemes_applied": applied,
                "total_redeemed": combined,
                "sale_amount_paid": new_paid,
                "sale_payment_status": sale.payment_status,
                "sale_outstanding": _round2(max(0.0, sale.final_amount - new_paid)),
                "redeemed_at": now.isoformat(),
                "recorded_by": current_user.id,
            },
        )

        await db.commit()

        # 9. Read back the authoritative post-commit position.
        balances = [
            await SchemeBalanceService.get_balance(db, current_user, row["enrollment_id"])
            for row in applied
        ]
        refreshed = await SaleRepository.get_by_id(db, sale.id, current_user.tenant_id)
        settled_paid = _round2(refreshed.amount_paid or 0)
        return MultiSchemeRedeemResponse(
            sale_id=refreshed.id,
            invoice_number=refreshed.invoice_number,
            total_redeemed=combined,
            sale_final_amount=_round2(refreshed.final_amount),
            sale_amount_paid=settled_paid,
            sale_outstanding=_round2(max(0.0, refreshed.final_amount - settled_paid)),
            sale_payment_status=refreshed.payment_status,
            balances=balances,
        )
