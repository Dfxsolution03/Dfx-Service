"""
JROS API Tests — SuperAdmin Platform Module (Module 14)
============================================================

Covers:
  GET /api/v1/superadmin/dashboard                     (SuperAdmin)
  GET /api/v1/superadmin/tenants                       (SuperAdmin)
  GET /api/v1/superadmin/tenants/{id}                   (SuperAdmin)
  PUT /api/v1/superadmin/tenants/{id}/status            (SuperAdmin)
  GET /api/v1/superadmin/tenants/{id}/statistics        (SuperAdmin)
  POST /api/v1/superadmin/tenants/provision              (SuperAdmin) — Module 29
"""

import base64
import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import unique_email, unique_phone

BASE = "/api/v1"

SUPERADMIN_ENDPOINTS_GET = [
    "/superadmin/dashboard",
    "/superadmin/tenants",
]

EXPORT_ENDPOINTS = [
    "/superadmin/export/dashboard",
    "/superadmin/export/tenants",
]


class TestSuperAdminAuth:

    @pytest.mark.parametrize("path", SUPERADMIN_ENDPOINTS_GET)
    async def test_no_auth_returns_401(self, client: AsyncClient, path: str):
        r = await client.get(f"{BASE}{path}")
        assert r.status_code == 401, r.text

    @pytest.mark.parametrize("path", SUPERADMIN_ENDPOINTS_GET)
    async def test_customer_role_returns_403(self, client: AsyncClient, path: str, customer_auth_headers: dict):
        r = await client.get(f"{BASE}{path}", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("path", SUPERADMIN_ENDPOINTS_GET)
    async def test_admin_role_returns_403(self, client: AsyncClient, path: str, admin_auth_headers: dict):
        """SuperAdmin platform routes exclude tenant Admins too."""
        r = await client.get(f"{BASE}{path}", headers=admin_auth_headers)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("path", SUPERADMIN_ENDPOINTS_GET)
    async def test_superadmin_returns_200(self, client: AsyncClient, path: str, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}{path}", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text


class TestPlatformDashboard:

    async def test_shape(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/superadmin/dashboard?period=this_year", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()["data"]["dashboard"]
        for field in [
            "total_tenants", "active_tenants", "total_customers", "total_schemes",
            "total_enrollments", "total_payments", "total_payment_amount",
            "growth_trend", "status_breakdown", "recent_tenants", "range",
        ]:
            assert field in d, f"Missing field: {field}"


class TestListTenants:

    async def test_includes_test_tenant(self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant):
        r = await client.get(f"{BASE}/superadmin/tenants", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        tenants = r.json()["data"]["tenants"]
        assert any(t["id"] == test_tenant.id for t in tenants)

    async def test_status_filter(self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant):
        r = await client.get(f"{BASE}/superadmin/tenants?status=Active", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        tenants = r.json()["data"]["tenants"]
        assert all(t["status"] == "Active" for t in tenants)

    async def test_includes_admin_contact_for_test_tenant(
        self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant, admin_user
    ):
        r = await client.get(f"{BASE}/superadmin/tenants", headers=superadmin_auth_headers)
        tenants = r.json()["data"]["tenants"]
        found = next(t for t in tenants if t["id"] == test_tenant.id)
        assert found["admin_name"] == admin_user.name


class TestTenantDetail:

    async def test_returns_detail(self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant):
        r = await client.get(f"{BASE}/superadmin/tenants/{test_tenant.id}", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        tenant = r.json()["data"]["tenant"]
        assert tenant["id"] == test_tenant.id
        assert tenant["slug"] == test_tenant.slug

    async def test_not_found_returns_404(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/superadmin/tenants/tnt_does_not_exist_xyz", headers=superadmin_auth_headers)
        assert r.status_code == 404, r.text

    async def test_no_auth_returns_401(self, client: AsyncClient, test_tenant):
        r = await client.get(f"{BASE}/superadmin/tenants/{test_tenant.id}")
        assert r.status_code == 401, r.text

    async def test_admin_role_returns_403(self, client: AsyncClient, admin_auth_headers: dict, test_tenant):
        r = await client.get(f"{BASE}/superadmin/tenants/{test_tenant.id}", headers=admin_auth_headers)
        assert r.status_code == 403, r.text


class TestSetTenantStatus:

    async def test_disable_then_enable(self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant):
        disable_r = await client.put(
            f"{BASE}/superadmin/tenants/{test_tenant.id}/status", json={"status": "Inactive"},
            headers=superadmin_auth_headers,
        )
        assert disable_r.status_code == 200, disable_r.text
        assert disable_r.json()["data"]["tenant"]["status"] == "Inactive"

        enable_r = await client.put(
            f"{BASE}/superadmin/tenants/{test_tenant.id}/status", json={"status": "Active"},
            headers=superadmin_auth_headers,
        )
        assert enable_r.status_code == 200, enable_r.text
        assert enable_r.json()["data"]["tenant"]["status"] == "Active"

    async def test_invalid_status_value_returns_400_or_422(
        self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant
    ):
        r = await client.put(
            f"{BASE}/superadmin/tenants/{test_tenant.id}/status", json={"status": "Trial"},
            headers=superadmin_auth_headers,
        )
        assert r.status_code in [400, 422], r.text

    async def test_not_found_returns_404(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.put(
            f"{BASE}/superadmin/tenants/tnt_does_not_exist_xyz/status", json={"status": "Active"},
            headers=superadmin_auth_headers,
        )
        assert r.status_code == 404, r.text

    async def test_no_auth_returns_401(self, client: AsyncClient, test_tenant):
        r = await client.put(f"{BASE}/superadmin/tenants/{test_tenant.id}/status", json={"status": "Active"})
        assert r.status_code == 401, r.text

    async def test_admin_role_returns_403(self, client: AsyncClient, admin_auth_headers: dict, test_tenant):
        r = await client.put(
            f"{BASE}/superadmin/tenants/{test_tenant.id}/status", json={"status": "Inactive"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 403, r.text

    async def test_creates_audit_log_entry(
        self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant
    ):
        await client.put(
            f"{BASE}/superadmin/tenants/{test_tenant.id}/status", json={"status": "Inactive"},
            headers=superadmin_auth_headers,
        )
        logs_r = await client.get(
            f"{BASE}/audit-logs?target_entity=tenants&action=TENANT_DISABLE&page_size=50",
            headers=superadmin_auth_headers,
        )
        logs = logs_r.json()["data"]["audit_logs"]["logs"]
        assert any(l["target_id"] == test_tenant.id for l in logs)

        # cleanup: restore to Active so other tests in this module see a clean state
        await client.put(
            f"{BASE}/superadmin/tenants/{test_tenant.id}/status", json={"status": "Active"},
            headers=superadmin_auth_headers,
        )


class _CapturingEmailProvider:
    """Same test-double shape as tests/api/test_auth.py's — a separate copy
    because it patches a different module's import of get_email_provider
    (app.services.superadmin_service, not app.services.auth_service)."""

    def __init__(self):
        self.sent = []

    async def send_email(self, *, to, subject, body_text, body_html=None):
        self.sent.append({"to": to, "subject": subject, "body_text": body_text, "body_html": body_html})


@pytest.fixture
def capturing_email_provider(monkeypatch):
    provider = _CapturingEmailProvider()
    monkeypatch.setattr("app.services.superadmin_service.get_email_provider", lambda: provider)
    return provider


def _provision_payload(**overrides) -> dict:
    uid = uuid.uuid4().hex[:8]
    payload = {
        "business_name": f"Provision Test Co {uid}",
        "subdomain": f"provision-test-{uid}",
        "business_address": "1 Test Lane, Bengaluru - 560001",
        "business_phone": unique_phone(),
        "contact_email": f"biz_{uid}@jros-test.com",
        "gst_number": None,
        "admin_name": "New Owner",
        "admin_email": unique_email(),
        "admin_phone": unique_phone(),
        "plan": "Professional",
        "trial_days": 14,
        "brand_color": "#2C6FBD",
    }
    payload.update(overrides)
    return payload


class TestProvisionTenantAuth:

    async def test_no_auth_returns_401(self, client: AsyncClient):
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=_provision_payload())
        assert r.status_code == 401, r.text

    async def test_customer_role_returns_403(self, client: AsyncClient, customer_auth_headers: dict):
        r = await client.post(
            f"{BASE}/superadmin/tenants/provision", json=_provision_payload(), headers=customer_auth_headers
        )
        assert r.status_code == 403, r.text

    async def test_admin_role_returns_403(self, client: AsyncClient, admin_auth_headers: dict):
        """Tenant provisioning is platform-wide — excludes tenant Admins too, same as every other /superadmin/* route."""
        r = await client.post(
            f"{BASE}/superadmin/tenants/provision", json=_provision_payload(), headers=admin_auth_headers
        )
        assert r.status_code == 403, r.text


class TestProvisionTenantSuccess:

    async def test_returns_201_with_full_shape(
        self, client: AsyncClient, superadmin_auth_headers: dict, capturing_email_provider
    ):
        payload = _provision_payload()
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        assert r.status_code == 201, r.text
        data = r.json()["data"]["provisioned"]

        assert data["tenant"]["name"] == payload["business_name"]
        assert data["tenant"]["slug"] == payload["subdomain"]
        assert data["tenant"]["status"] == "Active"
        assert data["branch"]["address"] == payload["business_address"]
        assert data["branch"]["phone"] == payload["business_phone"]
        assert payload["business_name"] in data["branch"]["name"]
        assert data["subscription"]["plan"] == "Professional"
        assert data["subscription"]["status"] == "Active"
        assert data["subscription"]["trial_ends_at"] is not None
        assert data["tenant"]["brand_color"] == payload["brand_color"]
        assert data["admin"]["email"] == payload["admin_email"]
        assert data["admin"]["name"] == payload["admin_name"]
        assert len(data["temporary_password"]) >= 10
        assert "token=" in data["activation_link"]
        assert data["onboarding_email_sent"] is True

    async def test_onboarding_email_is_sent_and_omits_the_password(
        self, client: AsyncClient, superadmin_auth_headers: dict, capturing_email_provider
    ):
        payload = _provision_payload()
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        data = r.json()["data"]["provisioned"]

        assert len(capturing_email_provider.sent) == 1
        sent = capturing_email_provider.sent[0]
        assert sent["to"] == payload["admin_email"]
        assert "token=" in sent["body_text"]
        # Security requirement: the temporary password must never be logged
        # or emailed — only the activation link is. The console email
        # provider logs this exact body_text, so keeping the password out of
        # it is what actually keeps it out of logs too.
        assert data["temporary_password"] not in sent["body_text"]
        assert data["temporary_password"] not in (sent["body_html"] or "")

    async def test_new_admin_can_login_with_temporary_password(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        payload = _provision_payload()
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        provisioned = r.json()["data"]["provisioned"]

        login_r = await client.post(
            f"{BASE}/auth/login",
            json={"username": payload["admin_email"], "password": provisioned["temporary_password"]},
        )
        assert login_r.status_code == 200, login_r.text
        assert login_r.json()["data"]["access_token"]

    async def test_activation_link_reuses_the_real_reset_password_flow(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        """Proves the activation link isn't a separate mechanism — it's a
        real PasswordResetToken that the existing /auth/reset-password
        endpoint (Module 18) already knows how to consume."""
        payload = _provision_payload()
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        provisioned = r.json()["data"]["provisioned"]
        raw_token = provisioned["activation_link"].split("token=")[1]

        reset_r = await client.post(
            f"{BASE}/auth/reset-password", json={"token": raw_token, "new_password": "BrandNewPass@123"}
        )
        assert reset_r.status_code == 200, reset_r.text

        login_r = await client.post(
            f"{BASE}/auth/login", json={"username": payload["admin_email"], "password": "BrandNewPass@123"}
        )
        assert login_r.status_code == 200, login_r.text

    async def test_new_tenant_appears_in_list_with_admin_contact(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        payload = _provision_payload()
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        tenant_id = r.json()["data"]["provisioned"]["tenant"]["id"]

        list_r = await client.get(f"{BASE}/superadmin/tenants", headers=superadmin_auth_headers)
        found = next(t for t in list_r.json()["data"]["tenants"] if t["id"] == tenant_id)
        assert found["admin_email"] == payload["admin_email"]

    async def test_omitted_brand_color_gets_a_real_default(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        """'Create default branding' — a tenant provisioned without picking
        a color in the Branding step still gets a real, persisted value,
        not null/undefined."""
        payload = _provision_payload()
        del payload["brand_color"]
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        assert r.status_code == 201, r.text
        data = r.json()["data"]["provisioned"]
        assert data["tenant"]["brand_color"] is not None
        assert data["tenant"]["brand_color"].startswith("#")

    async def test_creates_audit_log_entry_for_every_step(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        payload = _provision_payload()
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        tenant_id = r.json()["data"]["provisioned"]["tenant"]["id"]

        for action, entity in [
            ("TENANT_CREATE", "tenants"),
            ("SUBSCRIPTION_CREATE", "subscriptions"),
            ("BRANCH_CREATE", "branches"),
            ("TENANT_ADMIN_CREATE", "users"),
        ]:
            logs_r = await client.get(
                f"{BASE}/audit-logs?action={action}&target_entity={entity}&page_size=50",
                headers=superadmin_auth_headers,
            )
            logs = logs_r.json()["data"]["audit_logs"]["logs"]
            assert any(l["tenant_id"] == tenant_id for l in logs), f"missing {action} audit log for {tenant_id}"


class TestProvisionTenantValidation:

    async def test_missing_required_fields_returns_422(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.post(
            f"{BASE}/superadmin/tenants/provision", json={"business_name": "X"}, headers=superadmin_auth_headers
        )
        assert r.status_code in [400, 422], r.text

    async def test_invalid_subdomain_pattern_returns_422(self, client: AsyncClient, superadmin_auth_headers: dict):
        payload = _provision_payload(subdomain="Not A Valid Slug!")
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_invalid_admin_email_returns_422(self, client: AsyncClient, superadmin_auth_headers: dict):
        payload = _provision_payload(admin_email="not-an-email")
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_invalid_brand_color_returns_422(self, client: AsyncClient, superadmin_auth_headers: dict):
        payload = _provision_payload(brand_color="blue")
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        assert r.status_code in [400, 422], r.text


class TestProvisionTenantDuplicatesAndRollback:

    async def test_duplicate_subdomain_returns_409(
        self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant
    ):
        payload = _provision_payload(subdomain=test_tenant.slug)
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        assert r.status_code == 409, r.text

    async def test_duplicate_admin_email_returns_409_and_leaves_no_partial_tenant(
        self, client: AsyncClient, superadmin_auth_headers: dict, admin_user
    ):
        payload = _provision_payload(admin_email=admin_user.email)
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        assert r.status_code == 409, r.text

        # Rollback proof: admin_email is validated last (after Tenant/Branch/
        # Subscription would be built), so this confirms nothing was ever
        # staged/committed for this attempt — the subdomain from this exact
        # failed request must not exist anywhere.
        list_r = await client.get(f"{BASE}/superadmin/tenants", headers=superadmin_auth_headers)
        tenants = list_r.json()["data"]["tenants"]
        assert not any(t["slug"] == payload["subdomain"] for t in tenants)

    async def test_duplicate_contact_email_returns_409(
        self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant, db_session
    ):
        test_tenant.contact_email = f"contact_{uuid.uuid4().hex[:8]}@jros-test.com"
        db_session.add(test_tenant)
        await db_session.commit()

        payload = _provision_payload(contact_email=test_tenant.contact_email)
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        assert r.status_code == 409, r.text

    async def test_duplicate_business_phone_returns_409(
        self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant, db_session
    ):
        test_tenant.contact_phone = unique_phone()
        db_session.add(test_tenant)
        await db_session.commit()

        payload = _provision_payload(business_phone=test_tenant.contact_phone)
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        assert r.status_code == 409, r.text

    async def test_duplicate_gst_number_returns_409(
        self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant, db_session
    ):
        test_tenant.gst_number = f"29ABCDE{uuid.uuid4().hex[:4].upper()}1Z5"
        db_session.add(test_tenant)
        await db_session.commit()

        payload = _provision_payload(gst_number=test_tenant.gst_number)
        r = await client.post(f"{BASE}/superadmin/tenants/provision", json=payload, headers=superadmin_auth_headers)
        assert r.status_code == 409, r.text


class TestTenantStatistics:

    async def test_returns_statistics(self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant):
        r = await client.get(
            f"{BASE}/superadmin/tenants/{test_tenant.id}/statistics?period=this_month",
            headers=superadmin_auth_headers,
        )
        assert r.status_code == 200, r.text
        stats = r.json()["data"]["statistics"]
        assert stats["tenant_id"] == test_tenant.id
        for field in ["total_customers", "active_enrollments", "total_revenue", "total_gold_accumulated_grams"]:
            assert field in stats

    async def test_not_found_returns_404(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(
            f"{BASE}/superadmin/tenants/tnt_does_not_exist_xyz/statistics", headers=superadmin_auth_headers
        )
        assert r.status_code == 404, r.text

    async def test_admin_role_returns_403(self, client: AsyncClient, admin_auth_headers: dict, test_tenant):
        r = await client.get(
            f"{BASE}/superadmin/tenants/{test_tenant.id}/statistics", headers=admin_auth_headers
        )
        assert r.status_code == 403, r.text


class TestSuperAdminExportEndpointsAuth:
    """Shared auth/role/format behavior across every /superadmin/export/* endpoint."""

    @pytest.mark.parametrize("path", EXPORT_ENDPOINTS)
    async def test_no_auth_returns_401(self, client: AsyncClient, path: str):
        r = await client.get(f"{BASE}{path}")
        assert r.status_code == 401, r.text

    @pytest.mark.parametrize("path", EXPORT_ENDPOINTS)
    async def test_customer_role_returns_403(self, client: AsyncClient, path: str, customer_auth_headers: dict):
        r = await client.get(f"{BASE}{path}", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("path", EXPORT_ENDPOINTS)
    async def test_admin_role_returns_403(self, client: AsyncClient, path: str, admin_auth_headers: dict):
        """SuperAdmin platform export routes exclude tenant Admins too."""
        r = await client.get(f"{BASE}{path}", headers=admin_auth_headers)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("path", EXPORT_ENDPOINTS)
    @pytest.mark.parametrize("fmt", ["csv", "excel", "markdown"])
    async def test_superadmin_returns_200_for_every_format(
        self, client: AsyncClient, path: str, fmt: str, superadmin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}{path}?format={fmt}", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        export = r.json()["data"]["export"]
        assert export["format"] == fmt
        ext = {"csv": ".csv", "excel": ".xlsx", "markdown": ".md"}[fmt]
        assert export["filename"].endswith(ext)


class TestPlatformDashboardExportContent:
    async def test_content_has_kpi_rows(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/superadmin/export/dashboard?format=markdown", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        export = r.json()["data"]["export"]
        decoded = base64.b64decode(export["content_base64"]).decode("utf-8")
        for label in ["Total Tenants", "Active Tenants", "Total Customers", "Total Payments"]:
            assert label in decoded
        assert export["row_count"] == 7


class TestTenantsExportContent:
    async def test_content_reflects_seeded_tenant(self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant):
        r = await client.get(f"{BASE}/superadmin/export/tenants?format=csv", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        export = r.json()["data"]["export"]
        decoded = base64.b64decode(export["content_base64"]).decode("utf-8-sig")
        assert test_tenant.name in decoded

    async def test_status_filter_is_applied(self, client: AsyncClient, superadmin_auth_headers: dict, test_tenant):
        r = await client.get(
            f"{BASE}/superadmin/export/tenants?format=csv&status=Inactive", headers=superadmin_auth_headers
        )
        assert r.status_code == 200, r.text
        export = r.json()["data"]["export"]
        decoded = base64.b64decode(export["content_base64"]).decode("utf-8-sig")
        # test_tenant is Active by default, so it must not appear in an Inactive-only export.
        assert test_tenant.name not in decoded
