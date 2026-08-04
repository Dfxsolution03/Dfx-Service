"""
JROS API Tests — Scheme Endpoints
====================================

Covers:
  GET    /api/v1/schemes            → list schemes (Admin)
  GET    /api/v1/schemes/{id}       → get scheme (Admin)
  POST   /api/v1/schemes            → create scheme (Admin)
  PUT    /api/v1/schemes/{id}       → update scheme (Admin)
  DELETE /api/v1/schemes/{id}       → deactivate scheme (Admin, soft delete)
  GET    /api/v1/customer/schemes   → list active schemes (Customer)
"""

import pytest
from httpx import AsyncClient

BASE = "/api/v1"


def sample_scheme() -> dict:
    return {
        "name": "Monthly Gold Plan",
        "description": "Save monthly for 11 months",
        "monthly_amount": 1000,
        "duration_months": 11,
        "bonus_description": "8% bonus on maturity",
    }


# ═══════════════════════════════════════════════════════════
# 1. GET /schemes (Admin — List)
# ═══════════════════════════════════════════════════════════

class TestListSchemes:

    async def test_list_returns_empty_initially(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/schemes", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["schemes"] == []

    async def test_list_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/schemes")
        assert r.status_code == 401, r.text

    async def test_list_customer_role_returns_403(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/schemes", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    async def test_list_superadmin_role_returns_403(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        """SuperAdmin does NOT create or manage schemes (business rule)."""
        r = await client.get(f"{BASE}/schemes", headers=superadmin_auth_headers)
        assert r.status_code == 403, r.text


# ═══════════════════════════════════════════════════════════
# 2. POST /schemes (Admin — Create)
# ═══════════════════════════════════════════════════════════

class TestCreateScheme:

    async def test_create_returns_201(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/schemes", json=sample_scheme(), headers=admin_auth_headers)
        assert r.status_code == 201, r.text
        body = r.json()["data"]["scheme"]
        assert body["name"] == "Monthly Gold Plan"
        assert body["is_active"] is True
        assert body["tenant_id"] is not None
        assert body["created_by"] is not None

    async def test_create_negative_amount_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        payload = {**sample_scheme(), "monthly_amount": -100}
        r = await client.post(f"{BASE}/schemes", json=payload, headers=admin_auth_headers)
        assert r.status_code == 400, r.text

    async def test_create_zero_duration_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        payload = {**sample_scheme(), "duration_months": 0}
        r = await client.post(f"{BASE}/schemes", json=payload, headers=admin_auth_headers)
        assert r.status_code == 400, r.text

    async def test_create_missing_name_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        payload = sample_scheme()
        del payload["name"]
        r = await client.post(f"{BASE}/schemes", json=payload, headers=admin_auth_headers)
        assert r.status_code == 400, r.text

    async def test_create_short_name_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        payload = {**sample_scheme(), "name": "X"}
        r = await client.post(f"{BASE}/schemes", json=payload, headers=admin_auth_headers)
        assert r.status_code == 400, r.text

    async def test_create_no_auth_returns_401(self, client: AsyncClient):
        r = await client.post(f"{BASE}/schemes", json=sample_scheme())
        assert r.status_code == 401, r.text

    async def test_create_customer_role_returns_403(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/schemes", json=sample_scheme(), headers=customer_auth_headers)
        assert r.status_code == 403, r.text


# ═══════════════════════════════════════════════════════════
# 3. GET /schemes/{id} (Admin — Get One)
# ═══════════════════════════════════════════════════════════

class TestGetScheme:

    async def test_get_returns_200(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        create_r = await client.post(f"{BASE}/schemes", json=sample_scheme(), headers=admin_auth_headers)
        scheme_id = create_r.json()["data"]["scheme"]["id"]

        r = await client.get(f"{BASE}/schemes/{scheme_id}", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["scheme"]["id"] == scheme_id

    async def test_get_not_found_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/schemes/sch_does_not_exist", headers=admin_auth_headers)
        assert r.status_code == 404, r.text


# ═══════════════════════════════════════════════════════════
# 4. PUT /schemes/{id} (Admin — Update)
# ═══════════════════════════════════════════════════════════

class TestUpdateScheme:

    async def test_update_returns_200(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        create_r = await client.post(f"{BASE}/schemes", json=sample_scheme(), headers=admin_auth_headers)
        scheme_id = create_r.json()["data"]["scheme"]["id"]

        r = await client.put(
            f"{BASE}/schemes/{scheme_id}", json={"monthly_amount": 1500}, headers=admin_auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["scheme"]["monthly_amount"] == 1500

    async def test_update_not_found_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.put(
            f"{BASE}/schemes/sch_does_not_exist", json={"monthly_amount": 1500}, headers=admin_auth_headers
        )
        assert r.status_code == 404, r.text

    async def test_update_can_reactivate_via_is_active(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        create_r = await client.post(f"{BASE}/schemes", json=sample_scheme(), headers=admin_auth_headers)
        scheme_id = create_r.json()["data"]["scheme"]["id"]

        await client.delete(f"{BASE}/schemes/{scheme_id}", headers=admin_auth_headers)
        r = await client.put(
            f"{BASE}/schemes/{scheme_id}", json={"is_active": True}, headers=admin_auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["scheme"]["is_active"] is True


# ═══════════════════════════════════════════════════════════
# 5. DELETE /schemes/{id} (Admin — Soft Delete)
# ═══════════════════════════════════════════════════════════

class TestDeactivateScheme:

    async def test_deactivate_returns_200(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        create_r = await client.post(f"{BASE}/schemes", json=sample_scheme(), headers=admin_auth_headers)
        scheme_id = create_r.json()["data"]["scheme"]["id"]

        r = await client.delete(f"{BASE}/schemes/{scheme_id}", headers=admin_auth_headers)
        assert r.status_code == 200, r.text

    async def test_deactivate_is_soft_delete_row_still_exists(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        create_r = await client.post(f"{BASE}/schemes", json=sample_scheme(), headers=admin_auth_headers)
        scheme_id = create_r.json()["data"]["scheme"]["id"]

        await client.delete(f"{BASE}/schemes/{scheme_id}", headers=admin_auth_headers)

        # Row must still be fetchable by an admin (soft delete, not hard delete)
        get_r = await client.get(f"{BASE}/schemes/{scheme_id}", headers=admin_auth_headers)
        assert get_r.status_code == 200, get_r.text
        assert get_r.json()["data"]["scheme"]["is_active"] is False

    async def test_deactivate_not_found_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.delete(f"{BASE}/schemes/sch_does_not_exist", headers=admin_auth_headers)
        assert r.status_code == 404, r.text


# ═══════════════════════════════════════════════════════════
# 6. GET /customer/schemes (Customer — Active Only)
# ═══════════════════════════════════════════════════════════

class TestGetCustomerSchemes:

    async def test_returns_empty_when_none(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/schemes", headers=customer_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["schemes"] == []

    async def test_shows_active_scheme(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        await client.post(f"{BASE}/schemes", json=sample_scheme(), headers=admin_auth_headers)

        r = await client.get(f"{BASE}/customer/schemes", headers=customer_auth_headers)
        assert r.status_code == 200, r.text
        schemes = r.json()["data"]["schemes"]
        assert len(schemes) == 1
        # Customer-facing response must be lean — no internal admin/tenant IDs
        assert "tenant_id" not in schemes[0]
        assert "created_by" not in schemes[0]
        assert "is_active" not in schemes[0]

    async def test_hides_deactivated_scheme(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        create_r = await client.post(f"{BASE}/schemes", json=sample_scheme(), headers=admin_auth_headers)
        scheme_id = create_r.json()["data"]["scheme"]["id"]
        await client.delete(f"{BASE}/schemes/{scheme_id}", headers=admin_auth_headers)

        r = await client.get(f"{BASE}/customer/schemes", headers=customer_auth_headers)
        assert r.json()["data"]["schemes"] == []

    async def test_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/customer/schemes")
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 7. Tenant Isolation
# ═══════════════════════════════════════════════════════════

class TestSchemeTenantIsolation:

    async def test_other_tenant_admin_cannot_see_or_fetch_scheme(
        self, client: AsyncClient, admin_auth_headers: dict, db_session, test_tenant
    ):
        import uuid
        from sqlalchemy import select, delete
        from app.core.security import hash_password, create_access_token
        from app.core.constants import ROLE_ADMIN
        from app.models.auth import Tenant, Role, User
        from app.models.scheme import Scheme

        create_r = await client.post(f"{BASE}/schemes", json=sample_scheme(), headers=admin_auth_headers)
        scheme_id = create_r.json()["data"]["scheme"]["id"]

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
            list_r = await client.get(f"{BASE}/schemes", headers=other_headers)
            assert list_r.json()["data"]["schemes"] == [], "Cross-tenant scheme leakage in list"

            get_r = await client.get(f"{BASE}/schemes/{scheme_id}", headers=other_headers)
            assert get_r.status_code == 404, "Cross-tenant scheme leakage in get-by-id"
        finally:
            await db_session.execute(delete(Scheme).where(Scheme.tenant_id == other_tenant.id))
            await db_session.execute(delete(User).where(User.id == other_admin.id))
            await db_session.execute(delete(Tenant).where(Tenant.id == other_tenant.id))
            await db_session.commit()
