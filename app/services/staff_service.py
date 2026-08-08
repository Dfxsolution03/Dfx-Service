import uuid
from datetime import datetime, timezone
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.core.constants import ROLE_STAFF
from app.models.auth import User
from app.repositories.customer_repository import CustomerRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import ConflictException, ResourceNotFoundException, ForbiddenException
from app.schemas.staff import StaffCreateRequest, StaffStatusUpdateRequest, StaffResponse


class StaffService:
    """
    Phase 6C / Module 33 — Admin Staff Management. Reuses core.security's
    hash_password (the exact function auth_service.register_customer already
    uses) and CustomerRepository's User-adjacent queries — auth_service.py
    itself is never imported or modified. Role is always looked up as Staff
    server-side (StaffCreateRequest has no role field at all), so there is no
    input path that could create an Admin or SuperAdmin account here.
    """

    @staticmethod
    async def list_staff(db: AsyncSession, current_user: User) -> List[StaffResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        staff = await CustomerRepository.get_staff_by_tenant(db, current_user.tenant_id)
        return [StaffResponse.model_validate(s) for s in staff]

    @staticmethod
    async def create_staff(
        db: AsyncSession, current_user: User, req: StaffCreateRequest
    ) -> StaffResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        if not req.email and not req.phone:
            raise ConflictException("Either email or phone number must be provided")

        if req.email:
            existing_email = await CustomerRepository.get_user_by_email(db, req.email)
            if existing_email:
                raise ConflictException("An account with this email address already exists")

        if req.phone:
            existing_phone = await CustomerRepository.get_user_by_phone(db, req.phone)
            if existing_phone:
                raise ConflictException("An account with this mobile phone number already exists")

        role = await CustomerRepository.get_role_by_name(db, ROLE_STAFF)
        if not role:
            raise ResourceNotFoundException("Staff role configuration missing in database")

        staff_id = f"usr_{uuid.uuid4().hex[:12]}"
        staff_user = User(
            id=staff_id,
            tenant_id=current_user.tenant_id,
            role_id=role.id,
            email=req.email,
            phone=req.phone,
            hashed_password=hash_password(req.password),
            name=req.name,
            kyc_status="Pending",
            member_since=datetime.now(timezone.utc).strftime("%B %Y"),
            is_active=True,
        )
        await CustomerRepository.create_staff_user(db, staff_user)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="STAFF_CREATE",
            target_entity="users",
            target_id=staff_id,
            before_state=None,
            after_state={"name": req.name, "email": req.email, "phone": req.phone},
        )

        await db.commit()
        await db.refresh(staff_user)
        return StaffResponse.model_validate(staff_user)

    @staticmethod
    async def update_staff_status(
        db: AsyncSession, current_user: User, staff_id: str, req: StaffStatusUpdateRequest
    ) -> StaffResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        staff_user = await CustomerRepository.get_staff_by_id_for_tenant(
            db, current_user.tenant_id, staff_id
        )
        if not staff_user:
            raise ResourceNotFoundException(f"Staff member ID '{staff_id}' not found")

        before_state = {"is_active": staff_user.is_active}
        staff_user.is_active = req.is_active
        after_state = {"is_active": staff_user.is_active}

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="STAFF_STATUS_UPDATE",
            target_entity="users",
            target_id=staff_id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(staff_user)
        return StaffResponse.model_validate(staff_user)
