"""
JROS API Tests — Payment Endpoints (Infrastructure Only)
============================================================

Covers:
  GET  /api/v1/payments                     → list payments (Admin)
  GET  /api/v1/payments/{id}                 → get payment (Admin)
  POST /api/v1/payments/manual               → record manual payment (Admin)
  PUT  /api/v1/payments/{id}                 → update payment (Admin)
  GET  /api/v1/customer/payments             → list my payments (Customer, read-only)
  GET  /api/v1/customer/payments/{id}        → get my payment (Customer, read-only)
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


class TestCreateManualPayment:

    async def test_create_returns_201_defaults_to_success(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)

        r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": 1000, "payment_method": "CASH"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 201, r.text
        body = r.json()["data"]["payment"]
        assert body["payment_status"] == "SUCCESS"
        assert body["payment_reference"]
        assert body["passbook_entry_id"] is None
        assert body["gateway_name"] is None

    async def test_create_with_explicit_pending_status(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)

        r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": 1000, "payment_method": "CHEQUE", "payment_status": "PENDING"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["payment"]["payment_status"] == "PENDING"

    async def test_create_negative_amount_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)

        r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": -100, "payment_method": "CASH"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 400, r.text

    async def test_create_invalid_method_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)

        r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": 500, "payment_method": "BITCOIN"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 400, r.text

    async def test_create_invalid_status_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)

        r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": 500, "payment_method": "CASH", "payment_status": "MAYBE"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 400, r.text

    async def test_create_nonexistent_enrollment_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": "enr_does_not_exist", "amount": 500, "payment_method": "CASH"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 404, r.text

    async def test_create_no_auth_returns_401(self, client: AsyncClient):
        r = await client.post(f"{BASE}/payments/manual", json={"enrollment_id": "enr_x", "amount": 1, "payment_method": "CASH"})
        assert r.status_code == 401, r.text

    async def test_create_customer_role_returns_403(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": "enr_x", "amount": 1, "payment_method": "CASH"},
            headers=customer_auth_headers,
        )
        assert r.status_code == 403, r.text

    async def test_create_superadmin_role_returns_403(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": "enr_x", "amount": 1, "payment_method": "CASH"},
            headers=superadmin_auth_headers,
        )
        assert r.status_code == 403, r.text

    async def test_create_does_not_create_passbook_entry(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        """The core business rule of this module: no automatic passbook entry creation."""
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)

        r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": 1000, "payment_method": "CASH"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 201, r.text

        pb_r = await client.get(f"{BASE}/customer/passbooks/{enrollment_id}", headers=customer_auth_headers)
        assert pb_r.json()["data"]["passbook"]["entries"] == []
        assert pb_r.json()["data"]["passbook"]["summary"]["entry_count"] == 0


class TestListAndGetPayments:

    async def test_admin_list_includes_derived_names(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)
        await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": 1000, "payment_method": "UPI"},
            headers=admin_auth_headers,
        )

        r = await client.get(f"{BASE}/payments", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        payments = r.json()["data"]["payments"]
        assert len(payments) >= 1
        assert "customer_name" in payments[0]
        assert "scheme_name" in payments[0]

    async def test_customer_list_is_lean(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)
        await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": 1000, "payment_method": "UPI"},
            headers=admin_auth_headers,
        )

        r = await client.get(f"{BASE}/customer/payments", headers=customer_auth_headers)
        assert r.status_code == 200, r.text
        payments = r.json()["data"]["payments"]
        assert len(payments) == 1
        assert "tenant_id" not in payments[0]
        assert "gateway_name" not in payments[0]

    async def test_get_not_found_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        r1 = await client.get(f"{BASE}/payments/pay_does_not_exist", headers=admin_auth_headers)
        assert r1.status_code == 404, r1.text

        r2 = await client.get(f"{BASE}/customer/payments/pay_does_not_exist", headers=customer_auth_headers)
        assert r2.status_code == 404, r2.text

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
        create_r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": 1000, "payment_method": "UPI"},
            headers=admin_auth_headers,
        )
        payment_id = create_r.json()["data"]["payment"]["id"]

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

        r = await client.get(f"{BASE}/customer/payments/{payment_id}", headers=other_headers)
        assert r.status_code == 404, r.text


class TestUpdatePayment:

    async def test_update_status_and_remarks(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)
        create_r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": 1000, "payment_method": "UPI"},
            headers=admin_auth_headers,
        )
        payment_id = create_r.json()["data"]["payment"]["id"]

        r = await client.put(
            f"{BASE}/payments/{payment_id}",
            json={"payment_status": "REFUNDED", "remarks": "Duplicate entry"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()["data"]["payment"]
        assert body["payment_status"] == "REFUNDED"
        assert body["remarks"] == "Duplicate entry"

    async def test_update_not_found_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.put(
            f"{BASE}/payments/pay_does_not_exist", json={"remarks": "x"}, headers=admin_auth_headers
        )
        assert r.status_code == 404, r.text

    async def test_update_no_auth_returns_401(self, client: AsyncClient):
        r = await client.put(f"{BASE}/payments/pay_x", json={"remarks": "x"})
        assert r.status_code == 401, r.text

    async def test_update_does_not_create_passbook_entry(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        """Even a transition to SUCCESS via update must not auto-create a passbook entry."""
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)
        create_r = await client.post(
            f"{BASE}/payments/manual",
            json={"enrollment_id": enrollment_id, "amount": 1000, "payment_method": "CHEQUE", "payment_status": "PENDING"},
            headers=admin_auth_headers,
        )
        payment_id = create_r.json()["data"]["payment"]["id"]

        await client.put(f"{BASE}/payments/{payment_id}", json={"payment_status": "SUCCESS"}, headers=admin_auth_headers)

        pb_r = await client.get(f"{BASE}/customer/passbooks/{enrollment_id}", headers=customer_auth_headers)
        assert pb_r.json()["data"]["passbook"]["entries"] == []


class TestPaymentTenantIsolation:

    async def test_other_tenant_admin_cannot_create_or_see(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict, db_session, test_tenant
    ):
        import uuid
        from sqlalchemy import select, delete
        from app.core.security import hash_password, create_access_token
        from app.core.constants import ROLE_ADMIN
        from app.models.auth import Tenant, Role, User
        from app.models.payment import Payment

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
            create_r = await client.post(
                f"{BASE}/payments/manual",
                json={"enrollment_id": enrollment_id, "amount": 500, "payment_method": "CASH"},
                headers=other_headers,
            )
            assert create_r.status_code == 404, "Cross-tenant enrollment must not be usable for a manual payment"

            list_r = await client.get(f"{BASE}/payments", headers=other_headers)
            assert list_r.json()["data"]["payments"] == []
        finally:
            await db_session.execute(delete(Payment).where(Payment.tenant_id == other_tenant.id))
            await db_session.execute(delete(User).where(User.id == other_admin.id))
            await db_session.execute(delete(Tenant).where(Tenant.id == other_tenant.id))
            await db_session.commit()
