import uuid
from datetime import date
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.enrollment import SchemeEnrollment, STATUS_ACTIVE
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.scheme_repository import SchemeRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import ResourceNotFoundException, ConflictException, ForbiddenException, ValidationException
from app.schemas.enrollment import EnrollmentCreateRequest, EnrollmentResponse, CustomerEnrollmentResponse


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
