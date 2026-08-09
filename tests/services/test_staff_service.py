"""
JROS Service Tests — StaffService permissions + require_admin_or_staff_module

Covers the new granular Staff module-permission system: creating/updating a
Staff account's grants, and the RBAC dependency that enforces them.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.schemas.staff import StaffCreateRequest, StaffPermissionsUpdateRequest
from app.services.staff_service import StaffService
from app.permissions.dependencies import require_admin_or_staff_module
from app.exceptions.base import ForbiddenException, ResourceNotFoundException


class TestCreateStaffWithPermissions:

    async def test_create_with_permissions_persists_them(
        self, db_session: AsyncSession, admin_user: User
    ):
        staff = await StaffService.create_staff(
            db_session, admin_user,
            StaffCreateRequest(name="Perm Test", email="permtest_1@jros-test.com", password="TestPass@123", permissions=["customers", "kyc"]),
        )
        assert set(staff.permissions) == {"customers", "kyc"}

    async def test_create_with_no_permissions_defaults_empty(
        self, db_session: AsyncSession, admin_user: User
    ):
        staff = await StaffService.create_staff(
            db_session, admin_user,
            StaffCreateRequest(name="No Perms", email="permtest_2@jros-test.com", password="TestPass@123"),
        )
        assert staff.permissions == []

    async def test_invalid_module_rejected_at_schema_level(self):
        with pytest.raises(ValueError):
            StaffCreateRequest(name="Bad", email="x@jros-test.com", password="TestPass@123", permissions=["not_a_real_module"])


class TestUpdateStaffPermissions:

    async def test_update_replaces_full_set(
        self, db_session: AsyncSession, admin_user: User
    ):
        staff = await StaffService.create_staff(
            db_session, admin_user,
            StaffCreateRequest(name="Update Test", email="permtest_3@jros-test.com", password="TestPass@123", permissions=["customers"]),
        )
        updated = await StaffService.update_staff_permissions(
            db_session, admin_user, staff.id, StaffPermissionsUpdateRequest(permissions=["catalogue", "marketing"])
        )
        assert set(updated.permissions) == {"catalogue", "marketing"}

    async def test_nonexistent_staff_raises_not_found(
        self, db_session: AsyncSession, admin_user: User
    ):
        with pytest.raises(ResourceNotFoundException):
            await StaffService.update_staff_permissions(
                db_session, admin_user, "usr_does_not_exist_xyz", StaffPermissionsUpdateRequest(permissions=["customers"])
            )


class TestRequireAdminOrStaffModule:

    async def test_admin_always_allowed_regardless_of_module(
        self, db_session: AsyncSession, admin_user: User
    ):
        checker = require_admin_or_staff_module("customers")
        result = await _call_checker(checker, admin_user)
        assert result is admin_user

    async def test_staff_without_grant_is_rejected(
        self, db_session: AsyncSession, test_tenant, admin_user: User
    ):
        from tests.conftest import _TestSessionFactory  # noqa
        staff = await StaffService.create_staff(
            db_session, admin_user,
            StaffCreateRequest(name="Ungranted", email="permtest_4@jros-test.com", password="TestPass@123", permissions=["kyc"]),
        )
        # Re-fetch as a User with role eager-loaded, matching what get_current_user provides.
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        stmt = select(User).options(selectinload(User.role)).where(User.id == staff.id)
        staff_user = (await db_session.execute(stmt)).scalar_one()

        checker = require_admin_or_staff_module("customers")
        with pytest.raises(ForbiddenException):
            await _call_checker(checker, staff_user)

    async def test_staff_with_grant_is_allowed(
        self, db_session: AsyncSession, admin_user: User
    ):
        staff = await StaffService.create_staff(
            db_session, admin_user,
            StaffCreateRequest(name="Granted", email="permtest_5@jros-test.com", password="TestPass@123", permissions=["customers"]),
        )
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        stmt = select(User).options(selectinload(User.role)).where(User.id == staff.id)
        staff_user = (await db_session.execute(stmt)).scalar_one()

        checker = require_admin_or_staff_module("customers")
        result = await _call_checker(checker, staff_user)
        assert result is staff_user


async def _call_checker(checker, user: User) -> User:
    """require_admin_or_staff_module returns a FastAPI dependency function
    whose sole parameter is itself a Depends(get_current_user) — call it
    directly with the already-resolved user, bypassing the DI layer."""
    import inspect
    sig = inspect.signature(checker)
    param_name = list(sig.parameters.keys())[0]
    return await checker(**{param_name: user})
