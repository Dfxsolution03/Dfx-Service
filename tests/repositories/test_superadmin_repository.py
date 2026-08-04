"""
JROS Repository Tests — SuperAdminRepository (Module 14)
=============================================================

Covers:
  - get_tenants (status filter, limit)
  - get_tenant_by_id
  - get_primary_admin_for_tenant / get_primary_admins_for_tenants
  - get_tenant_status_counts
  - get_tenant_growth_trend
  - get_platform_entity_counts
"""

import uuid
from datetime import date, timedelta
from sqlalchemy import select

from app.models.auth import Tenant, Role, User
from app.models.scheme import Scheme
from app.models.enrollment import SchemeEnrollment
from app.models.payment import Payment
from app.core.constants import ROLE_ADMIN
from app.core.security import hash_password
from app.repositories.superadmin_repository import SuperAdminRepository

TODAY = date.today()


async def _create_admin_for_tenant(db_session, tenant_id, name="Test Admin") -> User:
    role = (await db_session.execute(select(Role).where(Role.name == ROLE_ADMIN))).scalar_one()
    uid = uuid.uuid4().hex[:8]
    user = User(
        id=f"usr_test_{uid}",
        tenant_id=tenant_id,
        role_id=role.id,
        email=f"admin_{uid}@jros-test.com",
        phone=None,
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

    async def test_includes_created_tenant(self, db_session, test_tenant):
        tenants = await SuperAdminRepository.get_tenants(db_session)
        assert any(t.id == test_tenant.id for t in tenants)

    async def test_status_filter(self, db_session, test_tenant):
        tenants = await SuperAdminRepository.get_tenants(db_session, status_filter="Active")
        assert all(t.status == "Active" for t in tenants)
        assert any(t.id == test_tenant.id for t in tenants)

    async def test_status_filter_excludes_non_matching(self, db_session, test_tenant):
        tenants = await SuperAdminRepository.get_tenants(db_session, status_filter="Inactive")
        assert all(t.id != test_tenant.id for t in tenants)

    async def test_limit_respected(self, db_session, test_tenant):
        tenants = await SuperAdminRepository.get_tenants(db_session, limit=1)
        assert len(tenants) <= 1


class TestGetTenantById:

    async def test_returns_tenant(self, db_session, test_tenant):
        result = await SuperAdminRepository.get_tenant_by_id(db_session, test_tenant.id)
        assert result is not None
        assert result.id == test_tenant.id

    async def test_nonexistent_returns_none(self, db_session):
        result = await SuperAdminRepository.get_tenant_by_id(db_session, "tnt_does_not_exist_xyz")
        assert result is None


class TestPrimaryAdmin:

    async def test_returns_none_when_no_admin(self, db_session, test_tenant):
        result = await SuperAdminRepository.get_primary_admin_for_tenant(db_session, test_tenant.id)
        assert result is None

    async def test_returns_admin_when_present(self, db_session, test_tenant):
        admin = await _create_admin_for_tenant(db_session, test_tenant.id)
        result = await SuperAdminRepository.get_primary_admin_for_tenant(db_session, test_tenant.id)
        assert result is not None
        assert result.id == admin.id

    async def test_bulk_lookup_returns_map(self, db_session, test_tenant):
        admin = await _create_admin_for_tenant(db_session, test_tenant.id)
        result = await SuperAdminRepository.get_primary_admins_for_tenants(db_session, [test_tenant.id, "tnt_other_xyz"])
        assert result.get(test_tenant.id) is not None
        assert result[test_tenant.id].id == admin.id
        assert "tnt_other_xyz" not in result

    async def test_bulk_lookup_empty_list_returns_empty_dict(self, db_session):
        result = await SuperAdminRepository.get_primary_admins_for_tenants(db_session, [])
        assert result == {}


class TestTenantStatusCounts:

    async def test_counts_reflect_tenant(self, db_session, test_tenant):
        counts = await SuperAdminRepository.get_tenant_status_counts(db_session)
        active_entry = next((c for c in counts if c["status"] == "Active"), None)
        assert active_entry is not None
        assert active_entry["count"] >= 1


class TestTenantGrowthTrend:

    async def test_includes_tenant_created_today(self, db_session, test_tenant):
        rows = await SuperAdminRepository.get_tenant_growth_trend(db_session, TODAY, TODAY, group_by_month=False)
        assert len(rows) >= 1
        assert sum(r["new_tenants"] for r in rows) >= 1

    async def test_excludes_out_of_range(self, db_session, test_tenant):
        far_past = TODAY - timedelta(days=1000)
        rows = await SuperAdminRepository.get_tenant_growth_trend(
            db_session, far_past - timedelta(days=10), far_past, group_by_month=False
        )
        assert sum(r["new_tenants"] for r in rows) == 0


class TestPlatformEntityCounts:

    async def test_counts_are_non_negative_integers(self, db_session, test_tenant):
        counts = await SuperAdminRepository.get_platform_entity_counts(db_session)
        assert counts["total_customers"] >= 0
        assert counts["total_schemes"] >= 0
        assert counts["total_enrollments"] >= 0
        assert counts["total_payments"] >= 0
        assert counts["total_payment_amount"] >= 0.0

    async def test_reflects_new_customer(self, db_session, test_tenant, customer_user):
        counts = await SuperAdminRepository.get_platform_entity_counts(db_session)
        assert counts["total_customers"] >= 1
