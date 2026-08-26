from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.enrollment import SchemeEnrollment
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.passbook_repository import PassbookRepository
from app.exceptions.base import ResourceNotFoundException, ForbiddenException
from app.schemas.passbook import (
    PassbookResponse,
    PassbookEnrollmentInfo,
    PassbookSchemeInfo,
    PassbookEntryResponse,
    PassbookSummary,
)


async def _build_passbook_response(
    db: AsyncSession, enrollment: SchemeEnrollment
) -> PassbookResponse:
    entries = await PassbookRepository.get_entries_by_enrollment(
        db, enrollment.id, enrollment.tenant_id
    )

    # Show the enrollment's RESOLVED terms (selected-tier snapshot when present,
    # else the scheme base) so the passbook reflects what this customer actually
    # pays and matures to — not a later-edited scheme default.
    from app.services.enrollment_service import resolve_enrollment_terms, maturity_amount
    eff_monthly, eff_duration = resolve_enrollment_terms(enrollment, enrollment.scheme)

    return PassbookResponse(
        enrollment=PassbookEnrollmentInfo(
            id=enrollment.id,
            enrollment_number=enrollment.enrollment_number,
            joined_date=enrollment.joined_date,
            status=enrollment.status,
            maturity_date=enrollment.maturity_date,
            scheme_tier_id=enrollment.scheme_tier_id,
        ),
        scheme=PassbookSchemeInfo(
            id=enrollment.scheme.id,
            name=enrollment.scheme.name,
            monthly_amount=eff_monthly,
            duration_months=eff_duration,
            maturity_amount=maturity_amount(eff_monthly, eff_duration),
            bonus_description=enrollment.scheme.bonus_description,
        ),
        entries=[PassbookEntryResponse.model_validate(e) for e in entries],
        summary=PassbookSummary(
            total_amount_paid=sum(e.amount for e in entries),
            total_gold_weight=sum(e.gold_weight for e in entries),
            entry_count=len(entries),
        ),
    )


class PassbookService:
    @staticmethod
    async def get_passbook_admin(
        db: AsyncSession, current_user: User, enrollment_id: str
    ) -> PassbookResponse:
        """Admin view — any enrollment belonging to their own tenant. Read-only."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        enrollment = await EnrollmentRepository.get_enrollment_by_id(
            db, enrollment_id, current_user.tenant_id
        )
        if not enrollment:
            raise ResourceNotFoundException(f"Enrollment ID '{enrollment_id}' not found")

        return await _build_passbook_response(db, enrollment)

    @staticmethod
    async def get_passbook_customer(
        db: AsyncSession, current_user: User, enrollment_id: str
    ) -> PassbookResponse:
        """Customer view — only their own enrollment's passbook."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        enrollment = await EnrollmentRepository.get_enrollment_by_id_for_customer(
            db, enrollment_id, current_user.tenant_id, current_user.id
        )
        if not enrollment:
            raise ResourceNotFoundException(f"Enrollment ID '{enrollment_id}' not found")

        return await _build_passbook_response(db, enrollment)
