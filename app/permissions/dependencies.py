from typing import Callable, Optional
from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.database import get_async_db
from app.core.security import decode_jwt_token
from app.core.tenant_context import set_current_tenant_id
from app.core.constants import (
    ROLE_ADMIN,
    ROLE_STAFF,
    ROLE_SUPERADMIN,
    ROLE_PERMISSIONS_MAP,
)
from app.exceptions.base import (
    UnauthorizedException,
    ForbiddenException,
)
from app.models.auth import User

security_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    db: AsyncSession = Depends(get_async_db),
) -> User:
    """
    Decodes Bearer JWT token, validates user existence and active status, and sets tenant context.
    Prevents privilege escalation by verifying tenant association for non-SuperAdmin roles.
    """
    if not credentials or not credentials.credentials:
        raise UnauthorizedException("Bearer authorization token is missing")

    token = credentials.credentials
    try:
        payload = decode_jwt_token(token)
    except ValueError as e:
        raise UnauthorizedException(f"Invalid or expired token: {str(e)}")

    if payload.get("type") != "access":
        raise UnauthorizedException("Token provided is not a valid access token")

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedException("Token payload invalid")

    # Query user with role eagerly loaded via a single JOIN (not a second
    # round trip) — this dependency runs on every authenticated request in
    # the app, so the round-trip count here directly multiplies across the
    # whole API surface. User.role is many-to-one, so joinedload can't
    # produce duplicate rows here.
    stmt = select(User).options(joinedload(User.role)).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise UnauthorizedException("User associated with token no longer exists")

    if not user.is_active:
        raise ForbiddenException("User account is inactive")

    # Tenant Scoping Verification
    if user.role.name != ROLE_SUPERADMIN and not user.tenant_id:
        raise ForbiddenException("Non-SuperAdmin user must be assigned to an active tenant")

    # Set tenant context variable for multi-tenant scoping
    set_current_tenant_id(user.tenant_id)

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


def require_permission(permission_code: str) -> Callable:
    """
    Dependency factory checking if the current user's role grants the requested permission.
    """
    async def permission_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role_name = current_user.role.name
        granted_permissions = ROLE_PERMISSIONS_MAP.get(user_role_name, [])

        if permission_code not in granted_permissions and user_role_name != ROLE_SUPERADMIN:
            raise ForbiddenException(
                f"Role '{user_role_name}' does not possess required permission '{permission_code}'"
            )
        return current_user

    return permission_checker


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Requires role to be Admin or SuperAdmin."""
    if current_user.role.name not in [ROLE_ADMIN, ROLE_SUPERADMIN]:
        raise ForbiddenException("Admin or SuperAdmin privileges required")
    return current_user


async def require_superadmin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Requires role to be SuperAdmin."""
    if current_user.role.name != ROLE_SUPERADMIN:
        raise ForbiddenException("SuperAdmin privileges required")
    return current_user


async def require_admin_only(
    current_user: User = Depends(get_current_user),
) -> User:
    """Requires role to be exactly Admin (excludes Staff, Customer, and SuperAdmin)."""
    if current_user.role.name != ROLE_ADMIN:
        raise ForbiddenException("Admin privileges required")
    return current_user


def require_admin_or_staff_module(*modules: str) -> Callable:
    """
    Admin/SuperAdmin: always allowed — unrestricted tenant access, never
    gated by staff_permissions.
    Staff: allowed only if the account was granted at least one of the given
    module keys (User.staff_permissions, comma-separated — see
    app/core/constants.py's STAFF_MODULE_* / ALL_STAFF_MODULES). Anyone else
    (Customer) is rejected outright, matching require_admin_only's scope.
    """
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        role_name = current_user.role.name
        if role_name in (ROLE_ADMIN, ROLE_SUPERADMIN):
            return current_user
        if role_name == ROLE_STAFF:
            granted = {m.strip() for m in (current_user.staff_permissions or "").split(",") if m.strip()}
            if granted.intersection(modules):
                return current_user
            raise ForbiddenException(
                f"Staff access to '{', '.join(modules)}' has not been granted for this account"
            )
        raise ForbiddenException("Admin privileges required")

    return checker
