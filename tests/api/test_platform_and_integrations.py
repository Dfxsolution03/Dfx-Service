"""
JROS API Tests — SuperAdmin Platform Settings, Integrations, Admin Notifications.

Covers:
  GET/PUT /api/v1/superadmin/platform/settings, .../status — SuperAdmin-only
  GET/PUT/POST /api/v1/superadmin/integrations/* — SuperAdmin-only, never leaks secrets
  POST/GET /api/v1/admin/notifications — Admin/staff-with-grant only, tenant-scoped
"""
from httpx import AsyncClient

BASE = "/api/v1"


class TestPlatformSettingsAuth:

    async def test_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/superadmin/platform/settings")
        assert r.status_code == 401, r.text

    async def test_admin_role_returns_403(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.get(f"{BASE}/superadmin/platform/settings", headers=admin_auth_headers)
        assert r.status_code == 403, r.text

    async def test_admin_cannot_update(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.put(f"{BASE}/superadmin/platform/settings", headers=admin_auth_headers, json={"platform_name": "Hacked"})
        assert r.status_code == 403, r.text

    async def test_superadmin_can_get_and_update(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/superadmin/platform/settings", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert "platform_name" in data
        assert "email_status" in data and "configured" in data["email_status"]

        r = await client.put(
            f"{BASE}/superadmin/platform/settings", headers=superadmin_auth_headers,
            json={"platform_name": "DFX Test Platform", "maintenance_mode": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["platform_name"] == "DFX Test Platform"
        assert r.json()["data"]["maintenance_mode"] is True

    async def test_status_endpoint_never_includes_secrets(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/superadmin/platform/settings/status", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        body_str = r.text.lower()
        assert "smtp_password" not in body_str
        assert "api_key" not in body_str


class TestIntegrationsAuth:

    async def test_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/superadmin/integrations")
        assert r.status_code == 401, r.text

    async def test_admin_role_returns_403(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.get(f"{BASE}/superadmin/integrations", headers=admin_auth_headers)
        assert r.status_code == 403, r.text

    async def test_customer_cannot_access_integrations(self, client: AsyncClient, customer_auth_headers: dict):
        r = await client.get(f"{BASE}/superadmin/integrations", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    async def test_superadmin_lists_providers_without_leaking_secrets(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/superadmin/integrations", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        items = r.json()["data"]["integrations"]
        assert len(items) >= 5
        for item in items:
            assert "api_key" not in item
            assert "secret" not in item
            assert set(item.keys()) >= {"provider", "configured", "enabled", "status"}

    async def test_enable_unconfigured_provider_returns_400(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.put(
            f"{BASE}/superadmin/integrations/whatsapp", headers=superadmin_auth_headers, json={"enabled": True}
        )
        assert r.status_code == 400, r.text

    async def test_test_connection_reports_not_configured_honestly(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        r = await client.post(f"{BASE}/superadmin/integrations/whatsapp/test", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "not_configured"

    async def test_unknown_provider_returns_404(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/superadmin/integrations/not_a_real_provider", headers=superadmin_auth_headers)
        assert r.status_code == 404, r.text


class TestWebhookSecretRevealOnce:

    async def test_create_returns_secret_once_list_never_does(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        r = await client.post(
            f"{BASE}/superadmin/webhooks", headers=superadmin_auth_headers,
            json={"url": "https://example.com/hook", "event_type": "payment.success"},
        )
        assert r.status_code == 201, r.text
        assert "signing_secret" in r.json()["data"]["webhook"]

        r2 = await client.get(f"{BASE}/superadmin/webhooks", headers=superadmin_auth_headers)
        assert r2.status_code == 200, r2.text
        for wh in r2.json()["data"]["webhooks"]:
            assert "signing_secret" not in wh
            assert "secret_hash" not in wh


class TestAdminNotificationsAuth:

    async def test_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/admin/notifications")
        assert r.status_code == 401, r.text

    async def test_customer_role_returns_403(self, client: AsyncClient, customer_auth_headers: dict):
        r = await client.get(f"{BASE}/admin/notifications", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    async def test_superadmin_cannot_reach_admin_notifications(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        """SuperAdmin has no tenant — require_admin_or_staff_module only ever
        admits Admin/Staff/SuperAdmin, but a real SuperAdmin token still has
        no tenant_id, so the service layer rejects it with 403, not a crash."""
        r = await client.post(
            f"{BASE}/admin/notifications", headers=superadmin_auth_headers,
            json={"title": "x", "body": "y", "channel": "IN_APP", "target_type": "ALL"},
        )
        assert r.status_code in (400, 403), r.text

    async def test_admin_can_create_and_send(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.post(
            f"{BASE}/admin/notifications", headers=admin_auth_headers,
            json={"title": "Welcome", "body": "Hello there", "channel": "IN_APP", "target_type": "ALL"},
        )
        assert r.status_code == 201, r.text
        campaign_id = r.json()["data"]["notification"]["id"]

        r2 = await client.post(f"{BASE}/admin/notifications/{campaign_id}/send", headers=admin_auth_headers)
        assert r2.status_code == 200, r2.text
        assert r2.json()["data"]["notification"]["status"] in ("SENT", "FAILED")
