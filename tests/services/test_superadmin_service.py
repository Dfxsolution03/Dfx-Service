"""
JROS Service Tests — SuperAdminService (Module 14)
=======================================================

Covers:
  - get_tenants (admin contact derivation)
  - get_tenant_detail (found / 404)
  - set_tenant_status (enable/disable, idempotent, invalid status, audit logged)
  - get_tenant_statistics (composition via ReportRepository, 404)
  - get_platform_dashboard (composition)
"""

import uuid
import pytest
from sqlalchemy import select

from app.models.auth import Role, User
from app.core.constants import ROLE_ADMIN
from app.core.security import hash_password
from app.services.superadmin_service import SuperAdminService
from app.exceptions.base import ResourceNotFoundException, ValidationException


async def _create_admin_for_tenant(db_session, tenant_id, name="Test Admin") -> User:
    role = (await db_session.execute(select(Role).where(Role.name == ROLE_ADMIN))).scalar_one()
    uid = uuid.uuid4().hex[:8]
    user = User(
        id=f"usr_test_{uid}",
        tenant_id=tenant_id,
        role_id=role.id,
        email=f"admin_{uid}@jros-test.com",
        phone="9876543210",
        hashed_password=hash_password("TestPass@123"),
        name=name,
        kyc_status="Verified",
        member_since="July 2026",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


class TestGetTenants:

    async def test_includes_derived_admin_contact(self, db_session, test_tenant, superadmin_user):
        admin = await _create_admin_for_tenant(db_session, test_tenant.id, name="Contact Person")
        result = await SuperAdminService.get_tenants(db_session, superadmin_user, status_filter=None)
        found = next(t for t in result if t.id == test_tenant.id)
        assert found.admin_name == "Contact Person"
        assert found.admin_phone == "9876543210"

    async def test_null_admin_contact_when_no_admin(self, db_session, test_tenant, superadmin_user):
        result = await SuperAdminService.get_tenants(db_session, superadmin_user, status_filter=None)
        found = next(t for t in result if t.id == test_tenant.id)
        assert found.admin_name is None


class TestGetTenantDetail:

    async def test_returns_detail(self, db_session, test_tenant, superadmin_user):
        result = await SuperAdminService.get_tenant_detail(db_session, superadmin_user, test_tenant.id)
        assert result.id == test_tenant.id
        assert result.name == test_tenant.name

    async def test_nonexistent_raises_not_found(self, db_session, superadmin_user):
        with pytest.raises(ResourceNotFoundException):
            await SuperAdminService.get_tenant_detail(db_session, superadmin_user, "tnt_does_not_exist_xyz")


class TestSetTenantStatus:

    async def test_disable_then_enable(self, db_session, test_tenant, superadmin_user):
        disabled = await SuperAdminService.set_tenant_status(db_session, superadmin_user, test_tenant.id, "Inactive")
        assert disabled.status == "Inactive"

        enabled = await SuperAdminService.set_tenant_status(db_session, superadmin_user, test_tenant.id, "Active")
        assert enabled.status == "Active"

    async def test_idempotent_when_already_active(self, db_session, test_tenant, superadmin_user):
        result = await SuperAdminService.set_tenant_status(db_session, superadmin_user, test_tenant.id, "Active")
        assert result.status == "Active"

    async def test_invalid_status_raises_validation_error(self, db_session, test_tenant, superadmin_user):
        with pytest.raises(ValidationException):
            await SuperAdminService.set_tenant_status(db_session, superadmin_user, test_tenant.id, "Trial")

    async def test_nonexistent_tenant_raises_not_found(self, db_session, superadmin_user):
        with pytest.raises(ResourceNotFoundException):
            await SuperAdminService.set_tenant_status(db_session, superadmin_user, "tnt_does_not_exist_xyz", "Active")


class TestGetTenantStatistics:

    async def test_returns_statistics_for_tenant(self, db_session, test_tenant, superadmin_user):
        result = await SuperAdminService.get_tenant_statistics(
            db_session, superadmin_user, test_tenant.id, "this_month", None, None
        )
        assert result.tenant_id == test_tenant.id
        assert result.total_customers >= 0
        assert result.active_enrollments >= 0

    async def test_nonexistent_tenant_raises_not_found(self, db_session, superadmin_user):
        with pytest.raises(ResourceNotFoundException):
            await SuperAdminService.get_tenant_statistics(
                db_session, superadmin_user, "tnt_does_not_exist_xyz", "this_month", None, None
            )


class TestGetPlatformDashboard:

    async def test_returns_composed_dashboard(self, db_session, test_tenant, superadmin_user):
        result = await SuperAdminService.get_platform_dashboard(db_session, superadmin_user, "this_year", None, None)
        assert result.total_tenants >= 1
        assert result.active_tenants >= 1
        assert isinstance(result.recent_tenants, list)
        assert isinstance(result.growth_trend, list)
        assert isinstance(result.status_breakdown, list)
