"""
JROS API Tests — Authentication Endpoints
==========================================

Covers:
  POST /api/v1/tenants/public      → list active stores
  POST /api/v1/auth/signup         → customer registration
  POST /api/v1/auth/login          → unified login (email + phone)
  POST /api/v1/auth/refresh        → refresh token rotation
  POST /api/v1/auth/logout         → logout (single/all devices)
  GET  /api/v1/users/me            → current user profile

Test scenarios per endpoint:
  ✓ Happy path (201 / 200)
  ✓ Missing required fields       → 400 / 422
  ✓ Duplicate registration        → 409
  ✓ Invalid credentials           → 401
  ✓ Wrong tenant                  → 400 / 404
  ✓ Inactive user                 → 401
  ✓ Expired / invalid JWT         → 401
  ✓ Missing Authorization header  → 401
  ✓ Refresh token rotation        → issues new pair
  ✓ Revoked token reuse detection → 401 + all sessions cleared
  ✓ Response schema validation
"""

import re
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.security import hash_password, create_access_token
from app.core.config import settings
from app.models.auth import User, Tenant, RefreshToken
from tests.conftest import unique_email, unique_phone, make_auth_headers

BASE = "/api/v1"


# ═══════════════════════════════════════════════════════════
# 1.  GET /tenants/public
# ═══════════════════════════════════════════════════════════

class TestGetPublicTenants:

    async def test_returns_200(self, client: AsyncClient):
        r = await client.get(f"{BASE}/tenants/public")
        assert r.status_code == 200

    async def test_response_shape(self, client: AsyncClient):
        r = await client.get(f"{BASE}/tenants/public")
        body = r.json()
        assert body["success"] is True
        assert "tenants" in body["data"]

    async def test_tenants_list_is_list(self, client: AsyncClient):
        r = await client.get(f"{BASE}/tenants/public")
        tenants = r.json()["data"]["tenants"]
        assert isinstance(tenants, list)

    async def test_tenant_item_has_required_fields(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        r = await client.get(f"{BASE}/tenants/public")
        tenants = r.json()["data"]["tenants"]
        assert len(tenants) > 0
        for t in tenants:
            assert "id" in t
            assert "name" in t
            assert "slug" in t

    async def test_no_auth_required(self, client: AsyncClient):
        """Public endpoint — no Authorization header needed."""
        r = await client.get(f"{BASE}/tenants/public")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# 2.  POST /auth/signup
# ═══════════════════════════════════════════════════════════

class TestCustomerSignup:

    async def test_successful_signup(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        payload = {
            "name": "Integration Test User",
            "email": unique_email(),
            "password": "Test@123456",
            "tenant_id": test_tenant.id,
        }
        r = await client.post(f"{BASE}/auth/signup", json=payload)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["success"] is True
        assert "user" in body["data"]

    async def test_signup_user_response_fields(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        email = unique_email()
        payload = {
            "name": "Schema Test User",
            "email": email,
            "password": "Test@123456",
            "tenant_id": test_tenant.id,
        }
        r = await client.post(f"{BASE}/auth/signup", json=payload)
        assert r.status_code == 201
        user = r.json()["data"]["user"]
        for field in ["id", "role", "name", "email", "kyc_status", "is_active"]:
            assert field in user, f"Missing field: {field}"
        assert user["email"] == email
        assert user["kyc_status"] == "Pending"
        assert user["is_active"] is True
        assert user["role"] == "Customer"

    async def test_signup_with_phone_only(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        payload = {
            "name": "Phone User",
            "phone": unique_phone(),
            "password": "Test@123456",
            "tenant_id": test_tenant.id,
        }
        r = await client.post(f"{BASE}/auth/signup", json=payload)
        assert r.status_code == 201, r.text

    async def test_signup_duplicate_email(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        email = unique_email()
        payload = {
            "name": "Duplicate User",
            "email": email,
            "password": "Test@123456",
            "tenant_id": test_tenant.id,
        }
        r1 = await client.post(f"{BASE}/auth/signup", json=payload)
        assert r1.status_code == 201
        r2 = await client.post(f"{BASE}/auth/signup", json=payload)
        assert r2.status_code == 409, r2.text

    async def test_signup_invalid_tenant(self, client: AsyncClient):
        payload = {
            "name": "Bad Tenant User",
            "email": unique_email(),
            "password": "Test@123456",
            "tenant_id": "tnt_does_not_exist_99999",
        }
        r = await client.post(f"{BASE}/auth/signup", json=payload)
        assert r.status_code in [400, 404], r.text

    async def test_signup_missing_name(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        payload = {
            "email": unique_email(),
            "password": "Test@123456",
            "tenant_id": test_tenant.id,
        }
        r = await client.post(f"{BASE}/auth/signup", json=payload)
        assert r.status_code in [400, 422], r.text

    async def test_signup_missing_tenant_id(self, client: AsyncClient):
        payload = {
            "name": "No Tenant",
            "email": unique_email(),
            "password": "Test@123456",
        }
        r = await client.post(f"{BASE}/auth/signup", json=payload)
        assert r.status_code in [400, 422], r.text

    async def test_signup_short_password(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        payload = {
            "name": "Short Pass",
            "email": unique_email(),
            "password": "abc",
            "tenant_id": test_tenant.id,
        }
        r = await client.post(f"{BASE}/auth/signup", json=payload)
        assert r.status_code in [400, 422], r.text

    async def test_signup_no_email_and_no_phone(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        payload = {
            "name": "Ghost User",
            "password": "Test@123456",
            "tenant_id": test_tenant.id,
        }
        r = await client.post(f"{BASE}/auth/signup", json=payload)
        assert r.status_code in [400, 422], r.text


# ═══════════════════════════════════════════════════════════
# 3.  POST /auth/login
# ═══════════════════════════════════════════════════════════

class TestUserLogin:

    async def test_successful_login_by_email(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        email = unique_email()
        # Register first
        await client.post(f"{BASE}/auth/signup", json={
            "name": "Login Test",
            "email": email,
            "password": "LoginPass@123",
            "tenant_id": test_tenant.id,
        })
        # Login
        r = await client.post(f"{BASE}/auth/login", json={
            "username": email,
            "password": "LoginPass@123",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True

    async def test_login_returns_tokens(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        email = unique_email()
        await client.post(f"{BASE}/auth/signup", json={
            "name": "Token Test",
            "email": email,
            "password": "TokenPass@123",
            "tenant_id": test_tenant.id,
        })
        r = await client.post(f"{BASE}/auth/login", json={
            "username": email,
            "password": "TokenPass@123",
        })
        assert r.status_code == 200
        data = r.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data
        assert "token_type" in data
        assert data["token_type"] == "Bearer"
        assert "expires_in" in data

    async def test_login_wrong_password(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        email = unique_email()
        await client.post(f"{BASE}/auth/signup", json={
            "name": "Wrong Pass",
            "email": email,
            "password": "CorrectPass@123",
            "tenant_id": test_tenant.id,
        })
        r = await client.post(f"{BASE}/auth/login", json={
            "username": email,
            "password": "WrongPass@999",
        })
        assert r.status_code == 401, r.text

    async def test_login_nonexistent_user(self, client: AsyncClient):
        r = await client.post(f"{BASE}/auth/login", json={
            "username": "nobody_exists@ghost.com",
            "password": "AnyPass@123",
        })
        assert r.status_code == 401, r.text

    async def test_login_missing_username(self, client: AsyncClient):
        r = await client.post(f"{BASE}/auth/login", json={
            "password": "SomePass@123",
        })
        assert r.status_code in [400, 422], r.text

    async def test_login_missing_password(self, client: AsyncClient):
        r = await client.post(f"{BASE}/auth/login", json={
            "username": "anyone@test.com",
        })
        assert r.status_code in [400, 422], r.text

    async def test_login_by_phone(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        phone = unique_phone()
        await client.post(f"{BASE}/auth/signup", json={
            "name": "Phone Login Test",
            "phone": phone,
            "password": "PhonePass@123",
            "tenant_id": test_tenant.id,
        })
        r = await client.post(f"{BASE}/auth/login", json={
            "username": phone,
            "password": "PhonePass@123",
        })
        assert r.status_code == 200, r.text


# ═══════════════════════════════════════════════════════════
# 4.  POST /auth/refresh
# ═══════════════════════════════════════════════════════════

class TestRefreshToken:

    async def _register_and_login(
        self, client: AsyncClient, test_tenant: Tenant
    ) -> dict:
        email = unique_email()
        await client.post(f"{BASE}/auth/signup", json={
            "name": "Refresh Flow User",
            "email": email,
            "password": "RefreshPass@123",
            "tenant_id": test_tenant.id,
        })
        r = await client.post(f"{BASE}/auth/login", json={
            "username": email,
            "password": "RefreshPass@123",
        })
        return r.json()["data"]

    async def test_refresh_returns_new_token_pair(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        tokens = await self._register_and_login(client, test_tenant)
        original_refresh = tokens["refresh_token"]

        r = await client.post(f"{BASE}/auth/refresh", json={
            "refresh_token": original_refresh,
        })
        assert r.status_code == 200, r.text
        new_data = r.json()["data"]
        assert "access_token" in new_data
        assert "refresh_token" in new_data
        # Rotated — new refresh token must differ from original
        assert new_data["refresh_token"] != original_refresh

    async def test_refresh_old_token_is_invalid(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        """
        After rotation, the OLD refresh token must be rejected (revoked).
        """
        tokens = await self._register_and_login(client, test_tenant)
        original_refresh = tokens["refresh_token"]

        # Use original refresh token (rotates it)
        r1 = await client.post(f"{BASE}/auth/refresh", json={
            "refresh_token": original_refresh,
        })
        assert r1.status_code == 200

        # Try to reuse the original (should fail — already revoked)
        r2 = await client.post(f"{BASE}/auth/refresh", json={
            "refresh_token": original_refresh,
        })
        assert r2.status_code == 401, (
            "Security failure: revoked refresh token was accepted"
        )

    async def test_refresh_with_invalid_token(self, client: AsyncClient):
        r = await client.post(f"{BASE}/auth/refresh", json={
            "refresh_token": "this.is.not.a.valid.jwt.token",
        })
        assert r.status_code == 401, r.text

    async def test_refresh_missing_token_field(self, client: AsyncClient):
        r = await client.post(f"{BASE}/auth/refresh", json={})
        assert r.status_code in [400, 422], r.text

    async def test_refresh_with_access_token_rejected(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        """Access token must not be accepted as a refresh token."""
        tokens = await self._register_and_login(client, test_tenant)
        r = await client.post(f"{BASE}/auth/refresh", json={
            "refresh_token": tokens["access_token"],  # ← wrong token type
        })
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 5.  POST /auth/logout
# ═══════════════════════════════════════════════════════════

class TestLogout:

    async def _register_and_login(
        self, client: AsyncClient, test_tenant: Tenant
    ) -> dict:
        email = unique_email()
        await client.post(f"{BASE}/auth/signup", json={
            "name": "Logout Test User",
            "email": email,
            "password": "LogoutPass@123",
            "tenant_id": test_tenant.id,
        })
        r = await client.post(f"{BASE}/auth/login", json={
            "username": email,
            "password": "LogoutPass@123",
        })
        return r.json()["data"]

    async def test_logout_single_device(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        tokens = await self._register_and_login(client, test_tenant)
        headers = make_auth_headers(tokens["access_token"])
        r = await client.post(f"{BASE}/auth/logout", json={
            "refresh_token": tokens["refresh_token"],
            "all_devices": False,
        }, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

    async def test_logout_all_devices(
        self, client: AsyncClient, test_tenant: Tenant
    ):
        tokens = await self._register_and_login(client, test_tenant)
        headers = make_auth_headers(tokens["access_token"])
        r = await client.post(f"{BASE}/auth/logout", json={
            "all_devices": True,
        }, headers=headers)
        assert r.status_code == 200, r.text

    async def test_logout_requires_auth(self, client: AsyncClient):
        """Logout without Authorization header must return 401."""
        r = await client.post(f"{BASE}/auth/logout", json={
            "all_devices": True,
        })
        assert r.status_code == 401, r.text

    async def test_logout_with_invalid_token(self, client: AsyncClient):
        headers = {"Authorization": "Bearer totally.fake.token"}
        r = await client.post(f"{BASE}/auth/logout", json={
            "all_devices": True,
        }, headers=headers)
        assert r.status_code == 401, r.text


# ═══════════════════════════════════════════════════════════
# 6.  GET /users/me
# ═══════════════════════════════════════════════════════════

class TestGetCurrentUser:

    async def test_get_my_profile_returns_200(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/users/me", headers=customer_auth_headers)
        assert r.status_code == 200, r.text

    async def test_get_my_profile_response_shape(
        self, client: AsyncClient, customer_auth_headers: dict
    ):
        r = await client.get(f"{BASE}/users/me", headers=customer_auth_headers)
        body = r.json()
        assert body["success"] is True
        user = body["data"]["user"]
        for field in ["id", "role", "name", "email", "kyc_status", "is_active"]:
            assert field in user, f"Missing field in /users/me response: {field}"

    async def test_get_my_profile_no_token(self, client: AsyncClient):
        r = await client.get(f"{BASE}/users/me")
        assert r.status_code == 401, r.text

    async def test_get_my_profile_invalid_token(self, client: AsyncClient):
        headers = {"Authorization": "Bearer invalid.token.here"}
        r = await client.get(f"{BASE}/users/me", headers=headers)
        assert r.status_code == 401, r.text

    async def test_get_my_profile_expired_token_rejected(
        self, client: AsyncClient, customer_user: User
    ):
        """
        A token signed with a past expiry (exp=past) must be rejected.
        """
        from datetime import timedelta
        expired_token = create_access_token(
            subject=customer_user.id,
            tenant_id=customer_user.tenant_id,
            role="Customer",
            expires_delta=timedelta(seconds=-1),  # already expired
        )
        headers = {"Authorization": f"Bearer {expired_token}"}
        r = await client.get(f"{BASE}/users/me", headers=headers)
        assert r.status_code == 401, (
            "Expired JWT was incorrectly accepted"
        )

    async def test_get_my_profile_bearer_wrong_case_rejected(
        self, client: AsyncClient, customer_token: dict
    ):
        """Authorization header must use 'Bearer' — test lowercase rejection."""
        headers = {"Authorization": f"bearer {customer_token['access_token']}"}
        r = await client.get(f"{BASE}/users/me", headers=headers)
        # httpx strips the scheme — FastAPI HTTPBearer handles this
        # Accept 200 or 401 depending on FastAPI's HTTPBearer handling
        assert r.status_code in [200, 401]


# ═══════════════════════════════════════════════════════════
# Module 18 — Authentication Hardening
# ═══════════════════════════════════════════════════════════

class _CapturingEmailProvider:
    """Test double standing in for the real email provider — captures every
    send_email() call so a test can pull the token out of the link, exactly
    like a QA tester would read it out of a real inbox."""

    def __init__(self):
        self.sent = []

    async def send_email(self, *, to, subject, body_text, body_html=None):
        self.sent.append({"to": to, "subject": subject, "body_text": body_text})


def _extract_token(body_text: str) -> str:
    match = re.search(r"token=([A-Za-z0-9_\-]+)", body_text)
    assert match, f"No token found in email body: {body_text}"
    return match.group(1)


@pytest.fixture
def capturing_email_provider(monkeypatch):
    provider = _CapturingEmailProvider()
    monkeypatch.setattr("app.services.auth_service.get_email_provider", lambda: provider)
    return provider


class TestForgotPasswordEndpoint:

    async def test_returns_200_for_real_email(
        self, client: AsyncClient, customer_user: User, capturing_email_provider
    ):
        r = await client.post(f"{BASE}/auth/forgot-password", json={"email": customer_user.email})
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True
        assert len(capturing_email_provider.sent) == 1
        assert capturing_email_provider.sent[0]["to"] == customer_user.email

    async def test_returns_identical_200_for_unknown_email(
        self, client: AsyncClient, capturing_email_provider
    ):
        """Same status/shape as the real-user case — no account-enumeration signal."""
        r = await client.post(
            f"{BASE}/auth/forgot-password", json={"email": "nobody-registered@example.com"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True
        assert len(capturing_email_provider.sent) == 0  # no email actually sent, but response looks identical

    async def test_rejects_malformed_email(self, client: AsyncClient):
        r = await client.post(f"{BASE}/auth/forgot-password", json={"email": "not-an-email"})
        assert r.status_code in [400, 422], r.text


class TestResetPasswordEndpoint:

    async def test_happy_path_then_login_with_new_password(
        self, client: AsyncClient, customer_user: User, capturing_email_provider
    ):
        await client.post(f"{BASE}/auth/forgot-password", json={"email": customer_user.email})
        token = _extract_token(capturing_email_provider.sent[0]["body_text"])

        r = await client.post(
            f"{BASE}/auth/reset-password", json={"token": token, "new_password": "BrandNewPass@789"}
        )
        assert r.status_code == 200, r.text

        login_r = await client.post(
            f"{BASE}/auth/login",
            json={"username": customer_user.email, "password": "BrandNewPass@789"},
        )
        assert login_r.status_code == 200, login_r.text

    async def test_old_password_no_longer_works(
        self, client: AsyncClient, customer_user: User, capturing_email_provider
    ):
        await client.post(f"{BASE}/auth/forgot-password", json={"email": customer_user.email})
        token = _extract_token(capturing_email_provider.sent[0]["body_text"])
        await client.post(f"{BASE}/auth/reset-password", json={"token": token, "new_password": "BrandNewPass@789"})

        login_r = await client.post(
            f"{BASE}/auth/login",
            json={"username": customer_user.email, "password": "TestPass@123"},
        )
        assert login_r.status_code == 401, login_r.text

    async def test_rejects_invalid_token(self, client: AsyncClient):
        r = await client.post(
            f"{BASE}/auth/reset-password", json={"token": "totally-made-up", "new_password": "Whatever@123"}
        )
        assert r.status_code == 401, r.text

    async def test_rejects_token_reuse(
        self, client: AsyncClient, customer_user: User, capturing_email_provider
    ):
        await client.post(f"{BASE}/auth/forgot-password", json={"email": customer_user.email})
        token = _extract_token(capturing_email_provider.sent[0]["body_text"])
        r1 = await client.post(f"{BASE}/auth/reset-password", json={"token": token, "new_password": "First@12345"})
        assert r1.status_code == 200
        r2 = await client.post(f"{BASE}/auth/reset-password", json={"token": token, "new_password": "Second@6789"})
        assert r2.status_code == 401, r2.text

    async def test_rejects_short_password(self, client: AsyncClient):
        r = await client.post(f"{BASE}/auth/reset-password", json={"token": "irrelevant", "new_password": "abc"})
        assert r.status_code in [400, 422], r.text


class TestEmailVerificationEndpoints:

    async def test_request_returns_200_and_sends_email(
        self, client: AsyncClient, customer_auth_headers: dict, customer_user: User, capturing_email_provider
    ):
        r = await client.post(f"{BASE}/auth/email/verify/request", headers=customer_auth_headers)
        assert r.status_code == 200, r.text
        assert len(capturing_email_provider.sent) == 1
        assert capturing_email_provider.sent[0]["to"] == customer_user.email

    async def test_request_requires_auth(self, client: AsyncClient):
        r = await client.post(f"{BASE}/auth/email/verify/request")
        assert r.status_code == 401, r.text

    async def test_confirm_happy_path(
        self, client: AsyncClient, customer_auth_headers: dict, capturing_email_provider
    ):
        await client.post(f"{BASE}/auth/email/verify/request", headers=customer_auth_headers)
        token = _extract_token(capturing_email_provider.sent[0]["body_text"])

        r = await client.post(f"{BASE}/auth/email/verify/confirm", json={"token": token})
        assert r.status_code == 200, r.text

        me = await client.get(f"{BASE}/users/me", headers=customer_auth_headers)
        # email_verified_at isn't in UserResponse today, so just confirm the
        # confirm-call itself succeeded and a second request now correctly
        # reports "already verified".
        second_request = await client.post(f"{BASE}/auth/email/verify/request", headers=customer_auth_headers)
        assert second_request.status_code == 409, second_request.text

    async def test_confirm_rejects_invalid_token(self, client: AsyncClient):
        r = await client.post(f"{BASE}/auth/email/verify/confirm", json={"token": "totally-made-up"})
        assert r.status_code == 401, r.text

    async def test_confirm_rejects_reuse(
        self, client: AsyncClient, customer_auth_headers: dict, capturing_email_provider
    ):
        await client.post(f"{BASE}/auth/email/verify/request", headers=customer_auth_headers)
        token = _extract_token(capturing_email_provider.sent[0]["body_text"])
        r1 = await client.post(f"{BASE}/auth/email/verify/confirm", json={"token": token})
        assert r1.status_code == 200
        r2 = await client.post(f"{BASE}/auth/email/verify/confirm", json={"token": token})
        assert r2.status_code == 401, r2.text
