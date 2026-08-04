"""
JROS API Tests — Passbook Endpoints
=======================================

Covers:
  GET /api/v1/passbooks/{enrollment_id}            → get passbook (Admin, read-only)
  GET /api/v1/customer/passbooks/{enrollment_id}    → get my passbook (Customer)
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


async def _enroll(client: AsyncClient, customer_auth_headers: dict, scheme_id: str) -> str:
    r = await client.post(f"{BASE}/customer/enrollments", json={"scheme_id": scheme_id}, headers=customer_auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["data"]["enrollment"]["id"]


class TestGetCustomerPassbook:

    async def test_returns_empty_passbook_for_new_enrollment(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)

        r = await client.get(f"{BASE}/customer/passbooks/{enrollment_id}", headers=customer_auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()["data"]["passbook"]
        assert body["entries"] == []
        assert body["summary"] == {"total_amount_paid": 0.0, "total_gold_weight": 0.0, "entry_count": 0}
        assert body["enrollment"]["id"] == enrollment_id
        assert body["scheme"]["name"] == "Monthly Gold Plan"

    async def test_not_found_returns_404(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/passbooks/enr_does_not_exist", headers=customer_auth_headers)
        assert r.status_code == 404, r.text

    async def test_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/customer/passbooks/enr_x")
        assert r.status_code == 401, r.text

    async def test_other_customer_cannot_access(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict, db_session, test_tenant
    ):
        import uuid
        from sqlalchemy import select
        from app.core.security import hash_password, create_access_token
        from app.core.constants import ROLE_CUSTOMER
        from app.models.auth import Role, User

        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)

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

        r = await client.get(f"{BASE}/customer/passbooks/{enrollment_id}", headers=other_headers)
        assert r.status_code == 404, r.text


class TestGetAdminPassbook:

    async def test_admin_can_view_tenant_passbook(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)

        r = await client.get(f"{BASE}/passbooks/{enrollment_id}", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["passbook"]["entries"] == []

    async def test_not_found_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/passbooks/enr_does_not_exist", headers=admin_auth_headers)
        assert r.status_code == 404, r.text

    async def test_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/passbooks/enr_x")
        assert r.status_code == 401, r.text

    async def test_customer_role_returns_403(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/passbooks/enr_x", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    async def test_superadmin_role_returns_403(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        """Super Admin does not access tenant passbooks (business rule)."""
        r = await client.get(f"{BASE}/passbooks/enr_x", headers=superadmin_auth_headers)
        assert r.status_code == 403, r.text

    async def test_other_tenant_admin_cannot_access(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict, db_session
    ):
        import uuid
        from sqlalchemy import select, delete
        from app.core.security import hash_password, create_access_token
        from app.core.constants import ROLE_ADMIN
        from app.models.auth import Tenant, Role, User

        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)

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
            r = await client.get(f"{BASE}/passbooks/{enrollment_id}", headers=other_headers)
            assert r.status_code == 404, r.text
        finally:
            await db_session.execute(delete(User).where(User.id == other_admin.id))
            await db_session.execute(delete(Tenant).where(Tenant.id == other_tenant.id))
            await db_session.commit()
