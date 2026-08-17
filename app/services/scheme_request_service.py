"""Phase 2 — Scheme Request lifecycle service.

Owns the REQUESTED -> APPROVED / REJECTED workflow that gates scheme
enrollment behind an Admin decision and a verified KYC status. This is a GATE
only: it creates no money and holds no scheme-configuration of its own. The
authoritative financial record stays SchemeEnrollment, produced exactly once
at approval, inside the same transaction that flips the request to APPROVED.

Reuses existing infrastructure — SchemeRequestRepository, EnrollmentRepository,
the enrollment-number generator and month helper, SchemeRepository, and the
audit conventions. No second KYC system is introduced: the live gate is the
customer's User.kyc_status, re-read (row-locked) inside the approval txn so a
stale frontend value can never let an unverified customer through.
"""
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.auth import User
from app.models.enrollment import SchemeEnrollment, STATUS_ACTIVE
from app.models.scheme import (
    SchemeRequest,
    SCHEME_REQUEST_REQUESTED,
    SCHEME_REQUEST_APPROVED,
    SCHEME_REQUEST_REJECTED,
)
from app.repositories.scheme_repository import SchemeRepository, SchemeRequestRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.audit_repository import AuditRepository
from app.services.enrollment_service import _add_months, _generate_enrollment_number
from app.exceptions.base import (
    ResourceNotFoundException,
    ForbiddenException,
    ValidationException,
    ConflictException,
)
from app.schemas.scheme import SchemeRequestResponse

# The one authoritative KYC gate value. Matches User.kyc_status vocabulary
# ("Pending" | "Verified" | "Rejected"); no parallel KYC store is created.
KYC_STATUS_VERIFIED = "Verified"


def _to_response(req: SchemeRequest) -> SchemeRequestResponse:
    """Build the API shape from a request with customer/scheme/enrollment
    relationships already loaded. kyc_status_current is the LIVE value off the
    customer row (not the historical snapshot), so the Admin queue shows whether
    the gate would pass right now."""
    customer = req.customer
    scheme = req.scheme
    enrollment = req.enrollment
    return SchemeRequestResponse(
        id=req.id,
        customer_id=req.customer_id,
        customer_name=customer.name if customer else None,
        customer_code=customer.customer_code if customer else None,
        scheme_id=req.scheme_id,
        scheme_name=scheme.name if scheme else None,
        status=req.status,
        kyc_status_at_request=req.kyc_status_at_request,
        kyc_status_current=customer.kyc_status if customer else None,
        enrollment_id=req.enrollment_id,
        enrollment_number=enrollment.enrollment_number if enrollment else None,
        rejection_reason=req.rejection_reason,
        requested_by=req.requested_by,
        approved_by=req.approved_by,
        rejected_by=req.rejected_by,
        approved_at=req.approved_at,
        rejected_at=req.rejected_at,
        created_at=req.created_at,
    )


class SchemeRequestService:
    # ─── Customer: create request (mobile-initiated) ───

    @staticmethod
    async def create_request(
        db: AsyncSession, current_user: User, scheme_id: str
    ) -> SchemeRequestResponse:
        """Customer files a request to join a scheme. Creates a REQUESTED row
        only — never an enrollment. A KYC snapshot is stored for history; the
        binding gate is re-checked at approval, not here."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        tenant_id = current_user.tenant_id
        customer_id = current_user.id

        scheme = await SchemeRepository.get_scheme_by_id(db, scheme_id, tenant_id)
        if not scheme:
            raise ResourceNotFoundException(f"Scheme ID '{scheme_id}' not found")
        if not scheme.is_active:
            raise ValidationException("This scheme is not currently active and cannot accept requests")

        # No stacking of open requests for the same (tenant, customer, scheme).
        # A new request is allowed once any prior one is APPROVED/REJECTED.
        existing_pending = await SchemeRequestRepository.get_pending_for_scheme(
            db, tenant_id, customer_id, scheme_id
        )
        if existing_pending:
            raise ConflictException("You already have a pending request for this scheme")

        # Already actively enrolled — nothing to request.
        active_enrollment = await EnrollmentRepository.get_active_enrollment_for_scheme(
            db, tenant_id, customer_id, scheme_id
        )
        if active_enrollment:
            raise ConflictException("You already have an active enrollment in this scheme")

        request = SchemeRequest(
            id=f"scr_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            customer_id=customer_id,
            scheme_id=scheme_id,
            status=SCHEME_REQUEST_REQUESTED,
            kyc_status_at_request=current_user.kyc_status,
            requested_by=customer_id,
        )
        await SchemeRequestRepository.create(db, request)

        await AuditRepository.create_log(
            db,
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SCHEME_REQUEST_CREATE",
            target_entity="scheme_requests",
            target_id=request.id,
            before_state=None,
            after_state={"scheme_id": scheme_id, "kyc_status_at_request": current_user.kyc_status},
        )

        await db.commit()
        created = await SchemeRequestRepository.get_by_id(db, request.id, tenant_id)
        return _to_response(created)

    # ─── Customer: own request history ───

    @staticmethod
    async def list_my_requests(
        db: AsyncSession, current_user: User
    ) -> List[SchemeRequestResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        rows = await SchemeRequestRepository.list_by_customer(
            db, current_user.tenant_id, current_user.id
        )
        return [_to_response(r) for r in rows]

    # ─── Admin/Staff: queue ───

    @staticmethod
    async def list_requests(
        db: AsyncSession, current_user: User, status: Optional[str] = None
    ) -> List[SchemeRequestResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        if status is not None and status not in (
            SCHEME_REQUEST_REQUESTED, SCHEME_REQUEST_APPROVED, SCHEME_REQUEST_REJECTED,
        ):
            raise ValidationException(f"Invalid status filter '{status}'")
        rows = await SchemeRequestRepository.list_by_tenant(db, current_user.tenant_id, status)
        return [_to_response(r) for r in rows]

    # ─── Admin/Staff: approve (atomic — request + enrollment in one txn) ───

    @staticmethod
    async def approve_request(
        db: AsyncSession, current_user: User, request_id: str
    ) -> SchemeRequestResponse:
        """Approve a REQUESTED request and create its single enrollment atomically.

        Invariant: there is never an APPROVED request without an enrollment, nor
        an enrollment without its request flipped to APPROVED. Every failure path
        raises before commit, so the whole transaction rolls back together.
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        tenant_id = current_user.tenant_id

        # (1-4) Row-lock the request; concurrent approvals serialize here and the
        # loser sees status != REQUESTED below.
        request = await SchemeRequestRepository.get_by_id_for_update(db, request_id, tenant_id)
        if not request:
            raise ResourceNotFoundException(f"Scheme request '{request_id}' not found")
        if request.status != SCHEME_REQUEST_REQUESTED:
            raise ConflictException(
                f"Request is '{request.status}', not '{SCHEME_REQUEST_REQUESTED}' — cannot approve"
            )

        # (5-8) Re-read the customer under a row lock and re-check the LIVE KYC
        # gate — never trust the snapshot or any client-supplied value.
        customer = (
            await db.execute(
                select(User)
                .where(User.id == request.customer_id, User.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not customer:
            raise ResourceNotFoundException("Customer for this request no longer exists in this tenant")
        if customer.kyc_status != KYC_STATUS_VERIFIED:
            raise ValidationException(
                "Customer KYC is not verified — verify KYC before approving this request"
            )

        # (9) Scheme must still exist and be active.
        scheme = await SchemeRepository.get_scheme_by_id(db, request.scheme_id, tenant_id)
        if not scheme:
            raise ResourceNotFoundException(f"Scheme ID '{request.scheme_id}' not found")
        if not scheme.is_active:
            raise ValidationException("Scheme is no longer active and cannot be enrolled")

        # (10) No duplicate active enrollment for this scheme.
        existing = await EnrollmentRepository.get_active_enrollment_for_scheme(
            db, tenant_id, request.customer_id, request.scheme_id
        )
        if existing:
            raise ConflictException("Customer already has an active enrollment in this scheme")

        # (11-12) Create the enrollment using existing repository-level logic and
        # helpers — NOT enrollment_service.create_enrollment, which assumes the
        # caller is the customer and commits internally.
        today = date.today()
        enrollment = SchemeEnrollment(
            id=f"enr_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            customer_id=request.customer_id,
            scheme_id=scheme.id,
            enrollment_number=_generate_enrollment_number(),
            joined_date=today,  # the date the scheme was taken by the customer
            status=STATUS_ACTIVE,
            maturity_date=_add_months(today, scheme.duration_months),
            months_paid=0,
            next_due_date=today,  # first installment due from the join date
        )
        await EnrollmentRepository.create_enrollment(db, enrollment)

        # (13-15) Link + flip + audit. enrollment_id is UNIQUE, so even a race
        # that slipped past the lock could not tie two enrollments to one request.
        now = datetime.now(timezone.utc)
        request.enrollment_id = enrollment.id
        request.status = SCHEME_REQUEST_APPROVED
        request.approved_by = current_user.id
        request.approved_at = now

        await AuditRepository.create_log(
            db,
            tenant_id=tenant_id,
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
                "via_request_id": request.id,
            },
        )
        await AuditRepository.create_log(
            db,
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SCHEME_REQUEST_APPROVE",
            target_entity="scheme_requests",
            target_id=request.id,
            before_state={"status": SCHEME_REQUEST_REQUESTED},
            after_state={"status": SCHEME_REQUEST_APPROVED, "enrollment_id": enrollment.id},
        )

        # (16) Commit once — request flip + enrollment together, or neither.
        await db.commit()
        approved = await SchemeRequestRepository.get_by_id(db, request.id, tenant_id)
        return _to_response(approved)

    # ─── Admin/Staff: reject ───

    @staticmethod
    async def reject_request(
        db: AsyncSession, current_user: User, request_id: str, reason: str
    ) -> SchemeRequestResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        tenant_id = current_user.tenant_id

        reason = (reason or "").strip()
        if len(reason) < 3:
            raise ValidationException("A rejection reason is required")

        request = await SchemeRequestRepository.get_by_id_for_update(db, request_id, tenant_id)
        if not request:
            raise ResourceNotFoundException(f"Scheme request '{request_id}' not found")
        if request.status != SCHEME_REQUEST_REQUESTED:
            raise ConflictException(
                f"Request is '{request.status}', not '{SCHEME_REQUEST_REQUESTED}' — cannot reject"
            )

        request.status = SCHEME_REQUEST_REJECTED
        request.rejection_reason = reason
        request.rejected_by = current_user.id
        request.rejected_at = datetime.now(timezone.utc)

        await AuditRepository.create_log(
            db,
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SCHEME_REQUEST_REJECT",
            target_entity="scheme_requests",
            target_id=request.id,
            before_state={"status": SCHEME_REQUEST_REQUESTED},
            after_state={"status": SCHEME_REQUEST_REJECTED, "rejection_reason": reason},
        )

        await db.commit()
        rejected = await SchemeRequestRepository.get_by_id(db, request.id, tenant_id)
        return _to_response(rejected)
