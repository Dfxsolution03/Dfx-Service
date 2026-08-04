"""
JROS API Tests — Audit Log Module (Module 14)
=================================================

Covers:
  GET /api/v1/audit-logs (SuperAdmin) — pagination, filters, auth/role gating
"""

import base64

import pytest
from httpx import AsyncClient

BASE = "/api/v1"


class TestAuditLogsAuth:

    async def test_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/audit-logs")
        assert r.status_code == 401, r.text

    async def test_customer_role_returns_403(self, client: AsyncClient, customer_auth_headers: dict):
        r = await client.get(f"{BASE}/audit-logs", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    async def test_admin_role_returns_403(self, client: AsyncClient, admin_auth_headers: dict):
        """require_superadmin excludes Admin too — this is a SuperAdmin-only view."""
        r = await client.get(f"{BASE}/audit-logs", headers=admin_auth_headers)
        assert r.status_code == 403, r.text

    async def test_superadmin_returns_200(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/audit-logs", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True


class TestAuditLogsShape:

    async def test_response_has_logs_and_pagination(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/audit-logs?page_size=5", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()["data"]["audit_logs"]
        assert "logs" in body
        assert "pagination" in body
        assert body["pagination"]["page_size"] == 5

    async def test_reflects_action_via_kyc_flow(
        self, client: AsyncClient, superadmin_auth_headers: dict, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        # KYC_SUBMIT is a real, cheap action to trigger for a fresh audit trail entry.
        r = await client.post(
            f"{BASE}/customer/kyc", json={"doc_type": "PAN", "doc_number": "ABCDE1234F"},
            headers=customer_auth_headers,
        )
        assert r.status_code == 201, r.text

        logs_r = await client.get(f"{BASE}/audit-logs?action=KYC_SUBMIT&page_size=50", headers=superadmin_auth_headers)
        assert logs_r.status_code == 200, logs_r.text
        logs = logs_r.json()["data"]["audit_logs"]["logs"]
        assert any(l["action"] == "KYC_SUBMIT" for l in logs)

    async def test_filters_by_target_entity(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/audit-logs?target_entity=kyc_records&page_size=50", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        logs = r.json()["data"]["audit_logs"]["logs"]
        assert all(l["target_entity"] == "kyc_records" for l in logs)

    async def test_invalid_page_size_returns_400_or_422(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/audit-logs?page_size=1000", headers=superadmin_auth_headers)
        assert r.status_code in [400, 422], r.text

    async def test_invalid_page_returns_400_or_422(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/audit-logs?page=0", headers=superadmin_auth_headers)
        assert r.status_code in [400, 422], r.text


class TestAuditLogsExportAuth:
    """Module 15 — reuses list_logs, so auth/role gating matches the list endpoint exactly."""

    async def test_no_auth_returns_401(self, client: AsyncClient):
        r = await client.get(f"{BASE}/audit-logs/export")
        assert r.status_code == 401, r.text

    async def test_customer_role_returns_403(self, client: AsyncClient, customer_auth_headers: dict):
        r = await client.get(f"{BASE}/audit-logs/export", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    async def test_admin_role_returns_403(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.get(f"{BASE}/audit-logs/export", headers=admin_auth_headers)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("fmt", ["csv", "excel", "markdown"])
    async def test_superadmin_returns_200_for_every_format(
        self, client: AsyncClient, fmt: str, superadmin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/audit-logs/export?format={fmt}", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
        export = r.json()["data"]["export"]
        assert export["format"] == fmt
        ext = {"csv": ".csv", "excel": ".xlsx", "markdown": ".md"}[fmt]
        assert export["filename"].endswith(ext)

    async def test_invalid_format_returns_400_or_422(self, client: AsyncClient, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}/audit-logs/export?format=pdf", headers=superadmin_auth_headers)
        assert r.status_code in [400, 422], r.text


class TestAuditLogsExportContent:

    async def test_content_reflects_filtered_action(
        self, client: AsyncClient, superadmin_auth_headers: dict, customer_auth_headers: dict
    ):
        r = await client.post(
            f"{BASE}/customer/kyc", json={"doc_type": "PAN", "doc_number": "EXPRT1234F"},
            headers=customer_auth_headers,
        )
        assert r.status_code == 201, r.text

        export_r = await client.get(
            f"{BASE}/audit-logs/export?action=KYC_SUBMIT&format=csv", headers=superadmin_auth_headers
        )
        assert export_r.status_code == 200, export_r.text
        export = export_r.json()["data"]["export"]
        decoded = base64.b64decode(export["content_base64"]).decode("utf-8-sig")
        assert "KYC_SUBMIT" in decoded
        assert "Log ID" in decoded and "Actor" in decoded
        assert export["row_count"] >= 1

    async def test_free_text_search_param_is_not_a_backend_filter(
        self, client: AsyncClient, superadmin_auth_headers: dict
    ):
        """No full-text search endpoint exists (see SESSION_HANDOFF.md Module 14) —
        an unrecognized `search` query param must be silently ignored, not error."""
        r = await client.get(f"{BASE}/audit-logs/export?search=anything", headers=superadmin_auth_headers)
        assert r.status_code == 200, r.text
