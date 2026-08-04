"""
JROS API Tests — Scheme Enrollment Endpoints
================================================

Covers:
  GET  /api/v1/enrollments                     → list enrollments (Admin, read-only)
  GET  /api/v1/enrollments/{id}                 → get enrollment (Admin, read-only)
  POST /api/v1/customer/enrollments             → enroll in a scheme (Customer)
  GET  /api/v1/customer/enrollments             → list my enrollments (Customer)
  GET  /api/v1/customer/enrollments/{id}        → get my enrollment (Customer)
"""

import pytest
from httpx import AsyncClient

BASE = "/api/v1"


async def _create_active_scheme(client: AsyncClient, admin_auth_headers: dict) -> str:
    r = await client.post(
        f"{BASE}/schemes",
        json={"name": "Monthly Gold Plan", "monthly_amount": 1000, "duration_months": 11},
        headers=admin_auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]["scheme"]["id"]


async def _create_inactive_scheme(client: AsyncClient, admin_auth_headers: dict) -> str:
    r = await client.post(
        f"{BASE}/schemes",
        json={"name": "Old Plan", "monthly_amount": 500, "duration_months": 6},
        headers=admin_auth_headers,
    )
    scheme_id = r.json()["data"]["scheme"]["id"]
    del_r = await client.delete(f"{BASE}/schemes/{scheme_id}", headers=admin_auth_headers)
    assert del_r.status_code == 200, del_r.text
    return scheme_id


# ═══════════════════════════════════════════════════════════
# 1. POST /customer/enrollments (Create)
# ═══════════════════════════════════════════════════════════

class TestCreateEnrollment:

    async def test_create_returns_201(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        r = await client.post(
            f"{BASE}/customer/enrollments", json={"scheme_id": scheme_id}, headers=customer_auth_headers
        )
        assert r.status_code == 201, r.text
        body = r.json()["data"]["enrollment"]
        assert body["scheme_id"] == scheme_id
        assert body["status"] == "ACTIVE"
        assert body["enrollment_number"]
        assert body["maturity_date"] > body["joined_date"]

    async def test_create_inactive_scheme_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_inactive_scheme(client, admin_auth_headers)
        r = await client.post(
            f"{BASE}/customer/enrollments", json={"scheme_id": scheme_id}, headers=customer_auth_headers
        )
        assert r.status_code == 400, r.text

    async def test_create_nonexistent_scheme_returns_404(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(
            f"{BASE}/customer/enrollments", json={"scheme_id": "sch_does_not_exist"}, headers=customer_auth_headers
        )
        assert r.status_code == 404, r.text

    async def test_create_duplicate_active_enrollment_returns_409(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        r1 = await client.post(
            f"{BASE}/customer/enrollments", json={"scheme_id": scheme_id}, headers=customer_auth_headers
        )
        assert r1.status_code == 201, r1.text

        r2 = await client.post(
            f"{BASE}/customer/enrollments", json={"scheme_id": scheme_id}, headers=customer_auth_headers
        )
        assert r2.status_code == 409, r2.text

    async def test_create_no_auth_returns_401(self, client: AsyncClient):
        r = await client.post(f"{BASE}/customer/enrollments", json={"scheme_id": "sch_x"})
        assert r.status_code == 401, r.text

    async def test_create_missing_scheme_id_returns_400(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/customer/enrollments", json={}, headers=customer_auth_headers)
        assert r.status_code == 400, r.text


# ═══════════════════════════════════════════════════════════
# 2. GET /customer/enrollments (List Mine)
# ═══════════════════════════════════════════════════════════

class TestListCustomerEnrollments:

    async def test_returns_empty_initially(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/enrollments", headers=customer_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["enrollments"] == []

    async def test_lists_own_enrollment(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        await client.post(f"{BASE}/customer/enrollments", json={"scheme_id": scheme_id}, headers=customer_auth_headers)

        r = await client.get(f"{BASE}/customer/enrollments", headers=customer_auth_headers)
        enrollments = r.json()["data"]["enrollments"]
        assert len(enrollments) == 1
        # Lean response — no tenant/customer IDs
        assert "tenant_id" not in enrollments[0]
        assert "customer_id" not in enrollments[0]

    async def test_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/customer/enrollments")
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 3. GET /customer/enrollments/{id} (Get Mine)
# ═══════════════════════════════════════════════════════════

class TestGetCustomerEnrollment:

    async def test_get_own_returns_200(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        create_r = await client.post(f"{BASE}/customer/enrollments", json={"scheme_id": scheme_id}, headers=customer_auth_headers)
        enrollment_id = create_r.json()["data"]["enrollment"]["id"]

        r = await client.get(f"{BASE}/customer/enrollments/{enrollment_id}", headers=customer_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["enrollment"]["id"] == enrollment_id

    async def test_get_not_found_returns_404(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/enrollments/enr_does_not_exist", headers=customer_auth_headers)
        assert r.status_code == 404, r.text


# ═══════════════════════════════════════════════════════════
# 4. Admin Endpoints (Read-Only)
# ═══════════════════════════════════════════════════════════

class TestAdminEnrollments:

    async def test_list_returns_all_tenant_enrollments(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        await client.post(f"{BASE}/customer/enrollments", json={"scheme_id": scheme_id}, headers=customer_auth_headers)

        r = await client.get(f"{BASE}/enrollments", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        enrollments = r.json()["data"]["enrollments"]
        assert len(enrollments) >= 1
        assert "customer_name" in enrollments[0]
        assert "scheme_name" in enrollments[0]

    async def test_get_by_id_returns_200(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        create_r = await client.post(f"{BASE}/customer/enrollments", json={"scheme_id": scheme_id}, headers=customer_auth_headers)
        enrollment_id = create_r.json()["data"]["enrollment"]["id"]

        r = await client.get(f"{BASE}/enrollments/{enrollment_id}", headers=admin_auth_headers)
        assert r.status_code == 200, r.text

    async def test_get_not_found_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/enrollments/enr_does_not_exist", headers=admin_auth_headers)
        assert r.status_code == 404, r.text

    async def test_list_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/enrollments")
        assert r.status_code == 401, r.text

    async def test_list_customer_role_returns_403(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/enrollments", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    async def test_list_superadmin_role_returns_403(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/enrollments", headers=superadmin_auth_headers)
        assert r.status_code == 403, r.text


# ═══════════════════════════════════════════════════════════
# 5. Cross-Customer / Cross-Tenant Isolation
# ═══════════════════════════════════════════════════════════

class TestEnrollmentIsolation:

    async def test_other_customer_cannot_access_enrollment(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict, db_session, test_tenant
    ):
        """A different customer in the SAME tenant must not see someone else's enrollment (404, not 403)."""
        import uuid
        from sqlalchemy import select
        from app.core.security import hash_password, create_access_token
        from app.core.constants import ROLE_CUSTOMER
        from app.models.auth import Role, User

        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        create_r = await client.post(f"{BASE}/customer/enrollments", json={"scheme_id": scheme_id}, headers=customer_auth_headers)
        enrollment_id = create_r.json()["data"]["enrollment"]["id"]

        uid = uuid.uuid4().hex[:8]
        role = (await db_session.execute(select(Role).where(Role.name == ROLE_CUSTOMER))).scalar_one()
        other_customer = User(
            id=f"usr_test_{uid}",
            tenant_id=test_tenant.id,
            role_id=role.id,
            email=f"other_{uid}@jros-test.com",
            phone=None,
            hashed_password=hash_password("TestPass@123"),
            name=f"Other Customer {uid}",
            kyc_status="Pending",
            member_since="July 2026",
            is_active=True,
        )
        db_session.add(other_customer)
        await db_session.commit()

        other_token = create_access_token(subject=other_customer.id, tenant_id=test_tenant.id, role=ROLE_CUSTOMER)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        r = await client.get(f"{BASE}/customer/enrollments/{enrollment_id}", headers=other_headers)
        assert r.status_code == 404, r.text

        list_r = await client.get(f"{BASE}/customer/enrollments", headers=other_headers)
        assert list_r.json()["data"]["enrollments"] == []
