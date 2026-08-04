"""
JROS API Tests — Reports Module
===================================

Covers:
  GET /api/v1/reports/dashboard-summary   (Admin)
  GET /api/v1/reports/payment-summary     (Admin)
  GET /api/v1/reports/top-customers       (Admin)
  GET /api/v1/reports/enrollment-summary  (Admin)
  GET /api/v1/reports/gold-rate-trend     (Admin)
  GET /api/v1/reports/scheme-summary      (Admin)
"""

import base64

import pytest
from httpx import AsyncClient

BASE = "/api/v1"

REPORT_ENDPOINTS = [
    "/reports/dashboard-summary",
    "/reports/payment-summary",
    "/reports/top-customers",
    "/reports/enrollment-summary",
    "/reports/gold-rate-trend",
    "/reports/scheme-summary",
]

EXPORT_ENDPOINTS = [
    "/reports/export/reports-summary",
    "/reports/export/analytics-summary",
    "/reports/export/dashboard-summary",
]


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


async def _record_payment(client: AsyncClient, admin_auth_headers: dict, enrollment_id: str, amount: float = 1000) -> None:
    r = await client.post(
        f"{BASE}/payments/manual",
        json={"enrollment_id": enrollment_id, "amount": amount, "payment_method": "CASH"},
        headers=admin_auth_headers,
    )
    assert r.status_code == 201, r.text


class TestReportEndpointsAuth:
    """Shared auth/role behavior across every /reports/* endpoint."""

    @pytest.mark.parametrize("path", REPORT_ENDPOINTS)
    async def test_no_auth_returns_401(self, client: AsyncClient, path: str):
        r = await client.get(f"{BASE}{path}")
        assert r.status_code == 401, r.text

    @pytest.mark.parametrize("path", REPORT_ENDPOINTS)
    async def test_customer_role_returns_403(self, client: AsyncClient, path: str, customer_auth_headers: dict):
        r = await client.get(f"{BASE}{path}", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("path", REPORT_ENDPOINTS)
    async def test_superadmin_role_returns_403(self, client: AsyncClient, path: str, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}{path}", headers=superadmin_auth_headers)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("path", REPORT_ENDPOINTS)
    async def test_admin_returns_200(self, client: AsyncClient, path: str, admin_auth_headers: dict):
        r = await client.get(f"{BASE}{path}", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

    @pytest.mark.parametrize("path", REPORT_ENDPOINTS)
    async def test_invalid_period_returns_400_or_422(self, client: AsyncClient, path: str, admin_auth_headers: dict):
        r = await client.get(f"{BASE}{path}?period=yesterday", headers=admin_auth_headers)
        assert r.status_code in [400, 422], r.text

    @pytest.mark.parametrize("path", REPORT_ENDPOINTS)
    async def test_custom_range_missing_date_to_returns_400(self, client: AsyncClient, path: str, admin_auth_headers: dict):
        r = await client.get(f"{BASE}{path}?date_from=2026-01-01", headers=admin_auth_headers)
        assert r.status_code == 400, r.text


class TestPaymentSummary:

    async def test_reflects_recorded_payment(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)
        await _record_payment(client, admin_auth_headers, enrollment_id, 1500)

        r = await client.get(f"{BASE}/reports/payment-summary?period=this_month", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        summary = r.json()["data"]["summary"]
        assert summary["total_revenue"] >= 1500
        assert summary["success_payment_count"] >= 1
        assert "pending_payment_count" in summary
        assert "monthly_trend" in summary
        assert "range" in summary and summary["range"]["label"] == "This Month"

    async def test_custom_range_shape(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.get(
            f"{BASE}/reports/payment-summary?date_from=2026-01-01&date_to=2026-01-31",
            headers=admin_auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["summary"]["range"]["label"] == "Custom Range"

    async def test_date_from_after_date_to_returns_400(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.get(
            f"{BASE}/reports/payment-summary?date_from=2026-02-01&date_to=2026-01-01",
            headers=admin_auth_headers,
        )
        assert r.status_code == 400, r.text


class TestTopCustomers:

    async def test_includes_recorded_investment(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)
        await _record_payment(client, admin_auth_headers, enrollment_id, 2500)

        r = await client.get(f"{BASE}/reports/top-customers?period=this_year", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        customers = r.json()["data"]["report"]["customers"]
        assert any(c["enrollment_id"] == enrollment_id and c["total_invested"] == 2500 for c in customers)

    async def test_limit_param_respected(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.get(f"{BASE}/reports/top-customers?period=this_year&limit=2", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        assert len(r.json()["data"]["report"]["customers"]) <= 2

    async def test_limit_out_of_range_returns_400_or_422(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.get(f"{BASE}/reports/top-customers?limit=100", headers=admin_auth_headers)
        assert r.status_code in [400, 422], r.text


class TestEnrollmentSummary:

    async def test_reflects_new_enrollment(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        await _enroll(client, customer_auth_headers, scheme_id)

        r = await client.get(f"{BASE}/reports/enrollment-summary?period=this_year", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        summary = r.json()["data"]["summary"]
        assert summary["active_count"] >= 1
        assert summary["conversion_funnel_percent"] is None
        assert summary["redemption_velocity_days"] is None
        assert "daily_trend" in summary


class TestDashboardSummary:

    async def test_reflects_customer_count_and_payment(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)
        await _record_payment(client, admin_auth_headers, enrollment_id, 4200)

        r = await client.get(f"{BASE}/reports/dashboard-summary?period=this_year", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        summary = r.json()["data"]["summary"]
        assert summary["total_revenue"] >= 4200
        assert summary["active_enrollments"] >= 1
        assert summary["total_customers"] >= 1
        assert "total_gold_accumulated_grams" in summary
        assert "total_customers_growth_percent" in summary


class TestGoldRateTrendAndSchemeSummary:

    async def test_gold_rate_trend_shape(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.get(f"{BASE}/reports/gold-rate-trend?period=this_month", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        report = r.json()["data"]["report"]
        assert "trend" in report
        assert "latest_change_percent" in report

    async def test_scheme_summary_reflects_created_scheme(
        self, client: AsyncClient, admin_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        r = await client.get(f"{BASE}/reports/scheme-summary?period=this_year", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        schemes = r.json()["data"]["report"]["schemes"]
        assert any(s["scheme_id"] == scheme_id for s in schemes)


class TestReportTenantIsolation:

    async def test_other_tenant_admin_sees_no_cross_tenant_data(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict, db_session, test_tenant
    ):
        import uuid
        from sqlalchemy import select, delete
        from app.core.security import hash_password, create_access_token
        from app.core.constants import ROLE_ADMIN
        from app.models.auth import Tenant, Role, User

        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)
        await _record_payment(client, admin_auth_headers, enrollment_id, 9999)

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
            r = await client.get(f"{BASE}/reports/payment-summary?period=this_year", headers=other_headers)
            assert r.status_code == 200, r.text
            assert r.json()["data"]["summary"]["total_revenue"] == 0.0
        finally:
            await db_session.execute(delete(User).where(User.id == other_admin.id))
            await db_session.execute(delete(Tenant).where(Tenant.id == other_tenant.id))
            await db_session.commit()


class TestReportExportEndpointsAuth:
    """Shared auth/role/format behavior across every /reports/export/* endpoint."""

    @pytest.mark.parametrize("path", EXPORT_ENDPOINTS)
    async def test_no_auth_returns_401(self, client: AsyncClient, path: str):
        r = await client.get(f"{BASE}{path}")
        assert r.status_code == 401, r.text

    @pytest.mark.parametrize("path", EXPORT_ENDPOINTS)
    async def test_customer_role_returns_403(self, client: AsyncClient, path: str, customer_auth_headers: dict):
        r = await client.get(f"{BASE}{path}", headers=customer_auth_headers)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("path", EXPORT_ENDPOINTS)
    async def test_superadmin_role_returns_403(self, client: AsyncClient, path: str, superadmin_auth_headers: dict):
        r = await client.get(f"{BASE}{path}", headers=superadmin_auth_headers)
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("path", EXPORT_ENDPOINTS)
    @pytest.mark.parametrize("fmt", ["csv", "excel", "markdown"])
    async def test_admin_returns_200_for_every_format(
        self, client: AsyncClient, path: str, fmt: str, admin_auth_headers: dict
    ):
        r = await client.get(f"{BASE}{path}?format={fmt}", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        export = r.json()["data"]["export"]
        assert export["format"] == fmt
        assert export["content_base64"]
        ext = {"csv": ".csv", "excel": ".xlsx", "markdown": ".md"}[fmt]
        assert export["filename"].endswith(ext)

    @pytest.mark.parametrize("path", EXPORT_ENDPOINTS)
    async def test_default_format_is_excel(self, client: AsyncClient, path: str, admin_auth_headers: dict):
        r = await client.get(f"{BASE}{path}", headers=admin_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["export"]["format"] == "excel"

    @pytest.mark.parametrize("path", EXPORT_ENDPOINTS)
    async def test_invalid_format_returns_400_or_422(self, client: AsyncClient, path: str, admin_auth_headers: dict):
        r = await client.get(f"{BASE}{path}?format=pdf", headers=admin_auth_headers)
        assert r.status_code in [400, 422], r.text


class TestReportsSummaryExportContent:
    async def test_content_reflects_recorded_investment(
        self, client: AsyncClient, admin_auth_headers: dict, customer_auth_headers: dict
    ):
        scheme_id = await _create_active_scheme(client, admin_auth_headers)
        enrollment_id = await _enroll(client, customer_auth_headers, scheme_id)
        await _record_payment(client, admin_auth_headers, enrollment_id, 3300)

        r = await client.get(
            f"{BASE}/reports/export/reports-summary?period=this_year&format=csv", headers=admin_auth_headers
        )
        assert r.status_code == 200, r.text
        export = r.json()["data"]["export"]
        decoded = base64.b64decode(export["content_base64"]).decode("utf-8-sig")
        assert "Customer Name" in decoded and "Total Invested" in decoded
        assert "3300" in decoded
        assert export["row_count"] >= 1


class TestAnalyticsSummaryExportContent:
    async def test_content_has_all_four_kpi_rows(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.get(
            f"{BASE}/reports/export/analytics-summary?format=markdown", headers=admin_auth_headers
        )
        assert r.status_code == 200, r.text
        export = r.json()["data"]["export"]
        decoded = base64.b64decode(export["content_base64"]).decode("utf-8")
        for label in ["Conversion Funnel", "Scheme Retention", "Avg Installment Size", "Redemption Velocity"]:
            assert label in decoded
        assert export["row_count"] == 4


class TestDashboardSummaryExportContent:
    async def test_content_has_kpi_rows(self, client: AsyncClient, admin_auth_headers: dict):
        r = await client.get(
            f"{BASE}/reports/export/dashboard-summary?format=markdown", headers=admin_auth_headers
        )
        assert r.status_code == 200, r.text
        export = r.json()["data"]["export"]
        decoded = base64.b64decode(export["content_base64"]).decode("utf-8")
        for label in ["Total Revenue", "Active Savings Schemes", "Gold Accumulated", "Total Customers"]:
            assert label in decoded
        assert export["row_count"] == 7
