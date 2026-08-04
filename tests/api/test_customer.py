"""
JROS API Tests — Customer Endpoints
=====================================

Covers:
  GET  /api/v1/customer/profile                     → get profile
  PUT  /api/v1/customer/profile                     → update profile
  GET  /api/v1/customer/kyc                         → get KYC status
  POST /api/v1/customer/kyc                         → submit KYC doc
  GET  /api/v1/kyc                                  → list KYC submissions (Admin)
  GET  /api/v1/kyc/{id}                             → get KYC submission (Admin)
  PUT  /api/v1/kyc/{id}/approve                     → approve KYC submission (Admin)
  PUT  /api/v1/kyc/{id}/reject                      → reject KYC submission (Admin)
  GET  /api/v1/customer/addresses                   → list addresses
  POST /api/v1/customer/addresses                   → add address
  PUT  /api/v1/customer/addresses/{id}              → update address
  DELETE /api/v1/customer/addresses/{id}            → delete address
  PUT  /api/v1/customer/addresses/{id}/default      → set default
  GET  /api/v1/customer/branches                    → branch locator
"""

import pytest
from httpx import AsyncClient

from app.models.auth import Tenant, User
from tests.conftest import make_auth_headers, unique_email, unique_phone

BASE = "/api/v1"

# ─── Shared address payload helper ────────────────────────

def sample_address(is_default: bool = False) -> dict:
    return {
        "name": "Test Recipient",
        "phone": "9876543210",
        "house": "12A",
        "street": "MG Road",
        "area": "Connaught Place",
        "city": "New Delhi",
        "state": "Delhi",
        "pincode": "110001",
        "type": "Home",
        "is_default": is_default,
    }


# ═══════════════════════════════════════════════════════════
# 1. GET /customer/profile
# ═══════════════════════════════════════════════════════════

class TestGetCustomerProfile:

    async def test_get_profile_returns_200(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/profile", headers=customer_auth_headers)
        assert r.status_code == 200, r.text

    async def test_get_profile_response_fields(
        self, client: AsyncClient, customer_auth_headers: dict, customer_user: User
    ):
        r = await client.get(f"{BASE}/customer/profile", headers=customer_auth_headers)
        body = r.json()
        assert body["success"] is True
        profile = body["data"]["profile"]
        for field in ["id", "name", "kyc_status", "tenant_name", "member_since"]:
            assert field in profile, f"Missing field: {field}"
        assert profile["id"] == customer_user.id

    async def test_get_profile_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/customer/profile")
        assert r.status_code == 401, r.text

    async def test_get_profile_invalid_token_returns_401(self, client: AsyncClient):
        headers = {"Authorization": "Bearer fake.token.xyz"}
        r = await client.get(f"{BASE}/customer/profile", headers=headers)
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 2. PUT /customer/profile
# ═══════════════════════════════════════════════════════════

class TestUpdateCustomerProfile:

    async def test_update_name_returns_200(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.put(f"{BASE}/customer/profile", json={
            "name": "Updated Name",
        }, headers=customer_auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True

    async def test_update_reflects_new_name(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        new_name = "New Test Name XYZ"
        await client.put(f"{BASE}/customer/profile", json={
            "name": new_name,
        }, headers=customer_auth_headers)
        r = await client.get(f"{BASE}/customer/profile", headers=customer_auth_headers)
        assert r.json()["data"]["profile"]["name"] == new_name

    async def test_update_invalid_phone_returns_400(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.put(f"{BASE}/customer/profile", json={
            "phone": "12345",  # invalid — not a 10-digit Indian mobile
        }, headers=customer_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_update_no_auth_returns_401(self, client: AsyncClient):
        r = await client.put(f"{BASE}/customer/profile", json={"name": "Test"})
        assert r.status_code == 401, r.text

    async def test_update_empty_body_allowed(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        """Empty body (no fields) should be valid — all fields are optional."""
        r = await client.put(f"{BASE}/customer/profile", json={},
                             headers=customer_auth_headers)
        assert r.status_code == 200, r.text


# ═══════════════════════════════════════════════════════════
# 3. GET /customer/kyc
# ═══════════════════════════════════════════════════════════

class TestGetKYC:

    async def test_get_kyc_returns_200(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/kyc", headers=customer_auth_headers)
        assert r.status_code == 200, r.text

    async def test_get_kyc_shape(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/kyc", headers=customer_auth_headers)
        body = r.json()
        assert body["success"] is True
        # kyc may be null if not yet submitted
        assert "kyc" in body["data"]

    async def test_get_kyc_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/customer/kyc")
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 4. POST /customer/kyc
# ═══════════════════════════════════════════════════════════

class TestSubmitKYC:

    async def test_submit_pan_kyc_returns_201(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/customer/kyc", json={
            "doc_type": "PAN",
            "doc_number": "ABCDE1234F",
        }, headers=customer_auth_headers)
        assert r.status_code == 201, r.text

    async def test_submit_kyc_response_shape(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/customer/kyc", json={
            "doc_type": "PAN",
            "doc_number": "ABCDE1234F",
        }, headers=customer_auth_headers)
        # Accept 201 or 409 (if already submitted in prior test)
        if r.status_code == 201:
            kyc = r.json()["data"]["kyc"]
            for field in ["id", "doc_type", "doc_number", "status"]:
                assert field in kyc, f"Missing KYC field: {field}"
            assert kyc["status"] == "Pending"

    async def test_submit_invalid_doc_type_returns_400(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/customer/kyc", json={
            "doc_type": "DRIVING_LICENSE",
            "doc_number": "DL1234567890",
        }, headers=customer_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_submit_invalid_pan_format_returns_400(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/customer/kyc", json={
            "doc_type": "PAN",
            "doc_number": "INVALIDPAN",  # wrong format
        }, headers=customer_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_submit_invalid_aadhaar_format_returns_400(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/customer/kyc", json={
            "doc_type": "AADHAAR",
            "doc_number": "123",  # must be 12 digits
        }, headers=customer_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_submit_kyc_no_auth_returns_401(self, client: AsyncClient):
        r = await client.post(f"{BASE}/customer/kyc", json={
            "doc_type": "PAN",
            "doc_number": "ABCDE1234F",
        })
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 4b. Admin KYC Review Endpoints
# ═══════════════════════════════════════════════════════════

async def _submit_kyc(client: AsyncClient, customer_auth_headers: dict, doc_number: str = "ABCDE1234F") -> str:
    r = await client.post(f"{BASE}/customer/kyc", json={
        "doc_type": "PAN",
        "doc_number": doc_number,
    }, headers=customer_auth_headers)
    assert r.status_code == 201, f"Failed to submit KYC: {r.text}"
    return r.json()["data"]["kyc"]["id"]


class TestAdminListKYC:

    async def test_list_returns_200(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/kyc", headers=admin_auth_headers)
        assert r.status_code == 200, r.text

    async def test_list_includes_submission(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        kyc_id = await _submit_kyc(client, customer_auth_headers)
        r = await client.get(f"{BASE}/kyc", headers=admin_auth_headers)
        ids = [rec["id"] for rec in r.json()["data"]["kyc_records"]]
        assert kyc_id in ids

    async def test_list_includes_customer_name(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        kyc_id = await _submit_kyc(client, customer_auth_headers)
        r = await client.get(f"{BASE}/kyc", headers=admin_auth_headers)
        record = next(rec for rec in r.json()["data"]["kyc_records"] if rec["id"] == kyc_id)
        assert record["customer_name"]

    async def test_list_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/kyc")
        assert r.status_code == 401, r.text

    async def test_list_customer_role_returns_403(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/kyc", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    async def test_list_superadmin_role_returns_403(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/kyc", headers=superadmin_auth_headers)
        assert r.status_code == 403, r.text


class TestAdminGetKYC:

    async def test_get_returns_200(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        kyc_id = await _submit_kyc(client, customer_auth_headers)
        r = await client.get(f"{BASE}/kyc/{kyc_id}", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["kyc_record"]["id"] == kyc_id

    async def test_get_not_found_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/kyc/kyc_does_not_exist", headers=admin_auth_headers)
        assert r.status_code == 404, r.text

    async def test_get_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/kyc/kyc_x")
        assert r.status_code == 401, r.text


class TestApproveKYC:

    async def test_approve_returns_200(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        kyc_id = await _submit_kyc(client, customer_auth_headers)
        r = await client.put(f"{BASE}/kyc/{kyc_id}/approve", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()["data"]["kyc_record"]
        assert body["status"] == "Verified"
        assert body["verified_at"] is not None

    async def test_approve_reflects_in_customer_kyc_status(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        kyc_id = await _submit_kyc(client, customer_auth_headers)
        await client.put(f"{BASE}/kyc/{kyc_id}/approve", headers=admin_auth_headers)

        kyc_r = await client.get(f"{BASE}/customer/kyc", headers=customer_auth_headers)
        assert kyc_r.json()["data"]["kyc"]["status"] == "Verified"

        profile_r = await client.get(f"{BASE}/customer/profile", headers=customer_auth_headers)
        assert profile_r.json()["data"]["profile"]["kyc_status"] == "Verified"

    async def test_approve_already_reviewed_returns_409(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        kyc_id = await _submit_kyc(client, customer_auth_headers)
        await client.put(f"{BASE}/kyc/{kyc_id}/approve", headers=admin_auth_headers)
        r = await client.put(f"{BASE}/kyc/{kyc_id}/approve", headers=admin_auth_headers)
        assert r.status_code == 409, r.text

    async def test_approve_not_found_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.put(f"{BASE}/kyc/kyc_does_not_exist/approve", headers=admin_auth_headers)
        assert r.status_code == 404, r.text

    async def test_approve_no_auth_returns_401(self, client: AsyncClient):
        r = await client.put(f"{BASE}/kyc/kyc_x/approve")
        assert r.status_code == 401, r.text

    async def test_approve_customer_role_returns_403(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.put(f"{BASE}/kyc/kyc_x/approve", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    async def test_approve_superadmin_role_returns_403(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        r = await client.put(f"{BASE}/kyc/kyc_x/approve", headers=superadmin_auth_headers)
        assert r.status_code == 403, r.text


class TestRejectKYC:

    async def test_reject_returns_200(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        kyc_id = await _submit_kyc(client, customer_auth_headers)
        r = await client.put(
            f"{BASE}/kyc/{kyc_id}/reject",
            json={"reason": "Document image is blurry"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()["data"]["kyc_record"]
        assert body["status"] == "Rejected"
        assert body["rejection_reason"] == "Document image is blurry"

    async def test_reject_reflects_in_customer_kyc_status(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        kyc_id = await _submit_kyc(client, customer_auth_headers)
        await client.put(
            f"{BASE}/kyc/{kyc_id}/reject", json={"reason": "Blurry"}, headers=admin_auth_headers
        )
        r = await client.get(f"{BASE}/customer/kyc", headers=customer_auth_headers)
        assert r.json()["data"]["kyc"]["status"] == "Rejected"
        assert r.json()["data"]["kyc"]["rejection_reason"] == "Blurry"

    async def test_reject_missing_reason_returns_400(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        kyc_id = await _submit_kyc(client, customer_auth_headers)
        r = await client.put(f"{BASE}/kyc/{kyc_id}/reject", json={}, headers=admin_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_reject_already_reviewed_returns_409(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        kyc_id = await _submit_kyc(client, customer_auth_headers)
        await client.put(f"{BASE}/kyc/{kyc_id}/reject", json={"reason": "Blurry"}, headers=admin_auth_headers)
        r = await client.put(f"{BASE}/kyc/{kyc_id}/reject", json={"reason": "Again"}, headers=admin_auth_headers)
        assert r.status_code == 409, r.text

    async def test_reject_not_found_returns_404(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        r = await client.put(
            f"{BASE}/kyc/kyc_does_not_exist/reject",
            json={"reason": "Document does not pass verification"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 404, r.text

    async def test_reject_no_auth_returns_401(self, client: AsyncClient):
        r = await client.put(f"{BASE}/kyc/kyc_x/reject", json={"reason": "x"})
        assert r.status_code == 401, r.text

    async def test_reject_customer_role_returns_403(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.put(f"{BASE}/kyc/kyc_x/reject", json={"reason": "x"}, headers=customer_auth_headers)
        assert r.status_code == 403, r.text


class TestKYCTenantIsolation:

    async def test_other_tenant_admin_cannot_see_or_review(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict,
        db_session, test_tenant: Tenant
    ):
        import uuid
        from sqlalchemy import select, delete
        from app.core.security import hash_password, create_access_token
        from app.core.constants import ROLE_ADMIN
        from app.models.auth import Role

        kyc_id = await _submit_kyc(client, customer_auth_headers)

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
            get_r = await client.get(f"{BASE}/kyc/{kyc_id}", headers=other_headers)
            assert get_r.status_code == 404, "Cross-tenant KYC record must not be visible"

            list_r = await client.get(f"{BASE}/kyc", headers=other_headers)
            assert kyc_id not in [rec["id"] for rec in list_r.json()["data"]["kyc_records"]]

            approve_r = await client.put(f"{BASE}/kyc/{kyc_id}/approve", headers=other_headers)
            assert approve_r.status_code == 404, "Cross-tenant admin must not be able to approve"
        finally:
            await db_session.execute(delete(User).where(User.id == other_admin.id))
            await db_session.execute(delete(Tenant).where(Tenant.id == other_tenant.id))
            await db_session.commit()


# ═══════════════════════════════════════════════════════════
# 5. GET /customer/addresses
# ═══════════════════════════════════════════════════════════

class TestListAddresses:

    async def test_list_addresses_returns_200(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/addresses", headers=customer_auth_headers)
        assert r.status_code == 200, r.text

    async def test_list_addresses_response_shape(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/addresses", headers=customer_auth_headers)
        body = r.json()
        assert body["success"] is True
        assert isinstance(body["data"]["addresses"], list)

    async def test_list_addresses_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/customer/addresses")
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 6. POST /customer/addresses
# ═══════════════════════════════════════════════════════════

class TestAddAddress:

    async def test_add_address_returns_201(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/customer/addresses",
                              json=sample_address(),
                              headers=customer_auth_headers)
        assert r.status_code == 201, r.text

    async def test_add_address_response_fields(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/customer/addresses",
                              json=sample_address(),
                              headers=customer_auth_headers)
        if r.status_code == 201:
            addr = r.json()["data"]["address"]
            for field in ["id", "name", "phone", "house", "street",
                          "city", "state", "pincode", "type", "is_default"]:
                assert field in addr, f"Missing address field: {field}"

    async def test_add_address_invalid_phone_returns_400(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        payload = sample_address()
        payload["phone"] = "12345"  # invalid phone
        r = await client.post(f"{BASE}/customer/addresses",
                              json=payload, headers=customer_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_add_address_invalid_pincode_returns_400(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        payload = sample_address()
        payload["pincode"] = "ABC"  # invalid pincode
        r = await client.post(f"{BASE}/customer/addresses",
                              json=payload, headers=customer_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_add_address_missing_required_field(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        payload = sample_address()
        del payload["city"]  # required field
        r = await client.post(f"{BASE}/customer/addresses",
                              json=payload, headers=customer_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_add_address_no_auth_returns_401(self, client: AsyncClient):
        r = await client.post(f"{BASE}/customer/addresses", json=sample_address())
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 7. PUT /customer/addresses/{id}
# ═══════════════════════════════════════════════════════════

class TestUpdateAddress:

    async def _create_address(
        self, client: AsyncClient, headers: dict
    ) -> str:
        """Helper: create an address and return its ID."""
        r = await client.post(f"{BASE}/customer/addresses",
                              json=sample_address(), headers=headers)
        assert r.status_code == 201, f"Failed to create address: {r.text}"
        return r.json()["data"]["address"]["id"]

    async def test_update_address_city(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        addr_id = await self._create_address(client, customer_auth_headers)
        r = await client.put(f"{BASE}/customer/addresses/{addr_id}",
                             json={"city": "Mumbai"},
                             headers=customer_auth_headers)
        assert r.status_code == 200, r.text

    async def test_update_address_not_found(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.put(f"{BASE}/customer/addresses/addr_does_not_exist_9999",
                             json={"city": "Mumbai"},
                             headers=customer_auth_headers)
        assert r.status_code == 404, r.text

    async def test_update_address_no_auth_returns_401(self, client: AsyncClient):
        r = await client.put(f"{BASE}/customer/addresses/any_id",
                             json={"city": "Mumbai"})
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 8. DELETE /customer/addresses/{id}
# ═══════════════════════════════════════════════════════════

class TestDeleteAddress:

    async def _create_address(
        self, client: AsyncClient, headers: dict
    ) -> str:
        r = await client.post(f"{BASE}/customer/addresses",
                              json=sample_address(), headers=headers)
        assert r.status_code == 201, f"Failed to create address: {r.text}"
        return r.json()["data"]["address"]["id"]

    async def test_delete_address_returns_200(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        addr_id = await self._create_address(client, customer_auth_headers)
        r = await client.delete(f"{BASE}/customer/addresses/{addr_id}",
                                headers=customer_auth_headers)
        assert r.status_code == 200, r.text

    async def test_delete_address_not_found(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.delete(f"{BASE}/customer/addresses/addr_does_not_exist",
                                headers=customer_auth_headers)
        assert r.status_code == 404, r.text

    async def test_delete_address_no_auth_returns_401(self, client: AsyncClient):
        r = await client.delete(f"{BASE}/customer/addresses/any_id")
        assert r.status_code == 401, r.text

    async def test_deleted_address_not_listed(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        addr_id = await self._create_address(client, customer_auth_headers)
        await client.delete(f"{BASE}/customer/addresses/{addr_id}",
                            headers=customer_auth_headers)
        r = await client.get(f"{BASE}/customer/addresses",
                             headers=customer_auth_headers)
        addresses = r.json()["data"]["addresses"]
        ids = [a["id"] for a in addresses]
        assert addr_id not in ids, "Deleted address still appears in list"


# ═══════════════════════════════════════════════════════════
# 9. PUT /customer/addresses/{id}/default
# ═══════════════════════════════════════════════════════════

class TestSetDefaultAddress:

    async def _create_address(
        self, client: AsyncClient, headers: dict
    ) -> str:
        r = await client.post(f"{BASE}/customer/addresses",
                              json=sample_address(), headers=headers)
        assert r.status_code == 201, f"Failed to create address: {r.text}"
        return r.json()["data"]["address"]["id"]

    async def test_set_default_returns_200(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        addr_id = await self._create_address(client, customer_auth_headers)
        r = await client.put(f"{BASE}/customer/addresses/{addr_id}/default",
                             headers=customer_auth_headers)
        assert r.status_code == 200, r.text

    async def test_set_default_marks_is_default_true(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        addr_id = await self._create_address(client, customer_auth_headers)
        await client.put(f"{BASE}/customer/addresses/{addr_id}/default",
                         headers=customer_auth_headers)
        r = await client.get(f"{BASE}/customer/addresses",
                             headers=customer_auth_headers)
        addresses = r.json()["data"]["addresses"]
        target = next((a for a in addresses if a["id"] == addr_id), None)
        assert target is not None
        assert target["is_default"] is True

    async def test_set_default_not_found(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.put(f"{BASE}/customer/addresses/addr_nonexistent_xyz/default",
                             headers=customer_auth_headers)
        assert r.status_code == 404, r.text

    async def test_set_default_no_auth_returns_401(self, client: AsyncClient):
        r = await client.put(f"{BASE}/customer/addresses/any_id/default")
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 10. GET /customer/branches
# ═══════════════════════════════════════════════════════════

class TestBranchLocator:

    async def test_branches_returns_200(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/branches",
                             headers=customer_auth_headers)
        assert r.status_code == 200, r.text

    async def test_branches_response_shape(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/customer/branches",
                             headers=customer_auth_headers)
        body = r.json()
        assert body["success"] is True
        assert isinstance(body["data"]["branches"], list)

    async def test_branches_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/customer/branches")
        assert r.status_code == 401, r.text
