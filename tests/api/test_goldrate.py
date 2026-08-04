"""
JROS API Tests — Gold Rate Endpoints
=======================================

Covers:
  GET  /api/v1/gold-rates/today       → get today's rate (Admin)
  POST /api/v1/gold-rates/today       → create today's rate (Admin)
  PUT  /api/v1/gold-rates/today       → update today's rate (Admin)
  GET  /api/v1/customer/gold-rate     → get today's rate (Customer)
"""

import pytest
from httpx import AsyncClient

from app.models.auth import User

BASE = "/api/v1"


# ═══════════════════════════════════════════════════════════
# 1. GET /gold-rates/today (Admin)
# ═══════════════════════════════════════════════════════════

class TestGetTodayRateAdmin:

    async def test_get_returns_null_when_none_set(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/gold-rates/today", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["rate"] is None

    async def test_get_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/gold-rates/today")
        assert r.status_code == 401, r.text

    async def test_get_customer_role_returns_403(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/gold-rates/today", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    async def test_get_superadmin_role_returns_403(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        """SuperAdmin does NOT manage tenant gold rates (business rule)."""
        r = await client.get(f"{BASE}/gold-rates/today", headers=superadmin_auth_headers)
        assert r.status_code == 403, r.text


# ═══════════════════════════════════════════════════════════
# 2. POST /gold-rates/today (Admin — Create)
# ═══════════════════════════════════════════════════════════

class TestCreateTodayRate:

    async def test_create_returns_201(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.post(
            f"{BASE}/gold-rates/today", json={"rate_24k": 9820.50}, headers=admin_auth_headers
        )
        assert r.status_code == 201, r.text
        body = r.json()["data"]["rate"]
        assert body["rate_24k"] == 9820.50
        assert body["tenant_id"] is not None
        assert body["created_by"] is not None

    async def test_create_duplicate_returns_409(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r1 = await client.post(
            f"{BASE}/gold-rates/today", json={"rate_24k": 9000}, headers=admin_auth_headers
        )
        assert r1.status_code == 201, r1.text

        r2 = await client.post(
            f"{BASE}/gold-rates/today", json={"rate_24k": 9500}, headers=admin_auth_headers
        )
        assert r2.status_code == 409, r2.text

    async def test_create_negative_rate_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.post(
            f"{BASE}/gold-rates/today", json={"rate_24k": -100}, headers=admin_auth_headers
        )
        assert r.status_code == 400, r.text

    async def test_create_zero_rate_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.post(
            f"{BASE}/gold-rates/today", json={"rate_24k": 0}, headers=admin_auth_headers
        )
        assert r.status_code == 400, r.text

    async def test_create_missing_field_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/gold-rates/today", json={}, headers=admin_auth_headers)
        assert r.status_code == 400, r.text

    async def test_create_no_auth_returns_401(self, client: AsyncClient):
        r = await client.post(f"{BASE}/gold-rates/today", json={"rate_24k": 9000})
        assert r.status_code == 401, r.text

    async def test_create_customer_role_returns_403(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(
            f"{BASE}/gold-rates/today", json={"rate_24k": 9000}, headers=customer_auth_headers
        )
        assert r.status_code == 403, r.text


# ═══════════════════════════════════════════════════════════
# 3. PUT /gold-rates/today (Admin — Update)
# ═══════════════════════════════════════════════════════════

class TestUpdateTodayRate:

    async def test_update_without_existing_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.put(
            f"{BASE}/gold-rates/today", json={"rate_24k": 9500}, headers=admin_auth_headers
        )
        assert r.status_code == 404, r.text

    async def test_update_modifies_existing_record_not_duplicate(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        create_r = await client.post(
            f"{BASE}/gold-rates/today", json={"rate_24k": 9000}, headers=admin_auth_headers
        )
        original_id = create_r.json()["data"]["rate"]["id"]

        update_r = await client.put(
            f"{BASE}/gold-rates/today", json={"rate_24k": 9500}, headers=admin_auth_headers
        )
        assert update_r.status_code == 200, update_r.text
        updated = update_r.json()["data"]["rate"]
        assert updated["id"] == original_id, "Update must modify the same row, not create a new one"
        assert updated["rate_24k"] == 9500

        # Confirm exactly one record exists for today via GET
        get_r = await client.get(f"{BASE}/gold-rates/today", headers=admin_auth_headers)
        assert get_r.json()["data"]["rate"]["id"] == original_id

    async def test_update_invalid_rate_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        await client.post(f"{BASE}/gold-rates/today", json={"rate_24k": 9000}, headers=admin_auth_headers)
        r = await client.put(
            f"{BASE}/gold-rates/today", json={"rate_24k": -5}, headers=admin_auth_headers
        )
        assert r.status_code == 400, r.text

    async def test_update_no_auth_returns_401(self, client: AsyncClient):
        r = await client.put(f"{BASE}/gold-rates/today", json={"rate_24k": 9000})
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 4. GET /customer/gold-rate (Customer)
# ═══════════════════════════════════════════════════════════

class TestGetCustomerGoldRate:

    async def test_get_returns_null_when_none_set(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/gold-rate", headers=customer_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["rate"] is None

    async def test_get_reflects_admin_set_rate(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        await client.post(f"{BASE}/gold-rates/today", json={"rate_24k": 9750.25}, headers=admin_auth_headers)

        r = await client.get(f"{BASE}/customer/gold-rate", headers=customer_auth_headers)
        assert r.status_code == 200, r.text
        rate = r.json()["data"]["rate"]
        assert rate["rate_24k"] == 9750.25
        # Customer-facing response must be lean — no internal admin/tenant IDs
        assert "created_by" not in rate
        assert "tenant_id" not in rate
        assert "id" not in rate

    async def test_get_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/customer/gold-rate")
        assert r.status_code == 401, r.text

    async def test_get_invalid_token_returns_401(self, client: AsyncClient):
        r = await client.get(
            f"{BASE}/customer/gold-rate", headers={"Authorization": "Bearer not.a.real.token"}
        )
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 5. Tenant Isolation
# ═══════════════════════════════════════════════════════════

class TestGoldRateTenantIsolation:

    async def test_admin_does_not_see_other_tenants_rate(
        self, client: AsyncClient, admin_auth_headers: dict, db_session, test_tenant
    ):
        """A second tenant's admin must never see this tenant's rate."""
        import uuid
        from sqlalchemy import select
        from app.core.security import hash_password, create_access_token
        from app.core.constants import ROLE_ADMIN
        from app.models.auth import Tenant, Role, User

        # Set a rate for the primary test tenant
        r1 = await client.post(f"{BASE}/gold-rates/today", json={"rate_24k": 9820}, headers=admin_auth_headers)
        assert r1.status_code == 201, r1.text

        # Create a second, isolated tenant + admin
        uid = uuid.uuid4().hex[:8]
        other_tenant = Tenant(id=f"tnt_test_{uid}", name=f"Other Store {uid}", slug=f"other-{uid}", status="Active")
        db_session.add(other_tenant)
        await db_session.commit()

        role = (await db_session.execute(select(Role).where(Role.name == ROLE_ADMIN))).scalar_one()
        other_admin = User(
            id=f"usr_test_{uid}",
            tenant_id=other_tenant.id,
            role_id=role.id,
            email=f"other_{uid}@jros-test.com",
            phone=None,
            hashed_password=hash_password("TestPass@123"),
            name=f"Other Admin {uid}",
            kyc_status="Verified",
            member_since="July 2026",
            is_active=True,
        )
        db_session.add(other_admin)
        await db_session.commit()

        other_token = create_access_token(subject=other_admin.id, tenant_id=other_tenant.id, role=ROLE_ADMIN)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        try:
            r2 = await client.get(f"{BASE}/gold-rates/today", headers=other_headers)
            assert r2.status_code == 200, r2.text
            assert r2.json()["data"]["rate"] is None, "Cross-tenant rate leakage detected"
        finally:
            from sqlalchemy import delete
            from app.models.goldrate import GoldRate
            await db_session.execute(delete(GoldRate).where(GoldRate.tenant_id == other_tenant.id))
            await db_session.execute(delete(User).where(User.id == other_admin.id))
            await db_session.execute(delete(Tenant).where(Tenant.id == other_tenant.id))
            await db_session.commit()
