import uuid
from datetime import datetime, timezone
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.core.constants import ROLE_STAFF, ALL_STAFF_MODULES, STAFF_MODULE_GROUPS
from app.models.auth import User
from app.repositories.customer_repository import CustomerRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import ConflictException, ResourceNotFoundException, ForbiddenException
from app.schemas.staff import (
    StaffCreateRequest,
    StaffStatusUpdateRequest,
    StaffPermissionsUpdateRequest,
    StaffResponse,
    StaffModuleInfo,
    StaffPermissionGroup,
    StaffPermissionCatalogResponse,
)


def _parse_permissions(staff_permissions: str | None) -> List[str]:
    if not staff_permissions:
        return []
    return [m.strip() for m in staff_permissions.split(",") if m.strip()]


def _serialize_permissions(permissions: List[str]) -> str | None:
    return ",".join(permissions) if permissions else None


def _to_response(user: User) -> StaffResponse:
    return StaffResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        is_active=user.is_active,
        member_since=user.member_since,
        permissions=_parse_permissions(user.staff_permissions),
        created_at=user.created_at,
    )


class StaffService:
    """
    Phase 6C / Module 33 — Admin Staff Management. Reuses core.security's
    hash_password (the exact function auth_service.register_customer already
    uses) and CustomerRepository's User-adjacent queries — auth_service.py
    itself is never imported or modified. Role is always looked up as Staff
    server-side (StaffCreateRequest has no role field at all), so there is no
    input path that could create an Admin or SuperAdmin account here.

    staff_permissions is stored as a comma-separated string on User (see
    app/models/auth.py) — parsed/serialized only here at the service
    boundary, same convention as CatalogueDesign.canvas_json.
    """

    @staticmethod
    def get_permission_catalog() -> StaffPermissionCatalogResponse:
        """The Scheme/Business grouped catalog for the Admin UI's two dropdowns.
        Built purely from STAFF_MODULE_GROUPS over the existing module keys —
        `all_modules` remains the authoritative validation set used by the
        assignment APIs (StaffCreateRequest / StaffPermissionsUpdateRequest)."""
        groups = [
            StaffPermissionGroup(
                group=g["group"],
                label=g["label"],
                modules=[StaffModuleInfo(key=m["key"], label=m["label"]) for m in g["modules"]],
            )
            for g in STAFF_MODULE_GROUPS
        ]
        return StaffPermissionCatalogResponse(groups=groups, all_modules=list(ALL_STAFF_MODULES))

    @staticmethod
    async def list_staff(db: AsyncSession, current_user: User) -> List[StaffResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        staff = await CustomerRepository.get_staff_by_tenant(db, current_user.tenant_id)
        return [_to_response(s) for s in staff]

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
            staff_permissions=_serialize_permissions(req.permissions),
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
            after_state={"name": req.name, "email": req.email, "phone": req.phone, "permissions": req.permissions},
        )

        await db.commit()
        await db.refresh(staff_user)
        return _to_response(staff_user)

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
        return _to_response(staff_user)

    @staticmethod
    async def update_staff_permissions(
        db: AsyncSession, current_user: User, staff_id: str, req: StaffPermissionsUpdateRequest
    ) -> StaffResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        staff_user = await CustomerRepository.get_staff_by_id_for_tenant(
            db, current_user.tenant_id, staff_id
        )
        if not staff_user:
            raise ResourceNotFoundException(f"Staff member ID '{staff_id}' not found")

        before_state = {"permissions": _parse_permissions(staff_user.staff_permissions)}
        staff_user.staff_permissions = _serialize_permissions(req.permissions)
        after_state = {"permissions": req.permissions}

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="STAFF_PERMISSIONS_UPDATE",
            target_entity="users",
            target_id=staff_id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(staff_user)
        return _to_response(staff_user)
