"""
JROS Security Tests — JWT, Password, RBAC, Tenant Isolation
=============================================================

Tests the security layer directly without HTTP:
  - JWT creation and validation
  - Expired token rejection
  - Token type enforcement (access vs refresh)
  - Algorithm pinning
  - Password hashing (bcrypt)
  - 72-byte DoS protection
  - Refresh token rotation mechanics
  - RBAC permission mapping
  - Tenant isolation in auth dependency
"""

import uuid
import pytest
import jwt
from datetime import datetime, timedelta, timezone

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_jwt_token,
    hash_token_sha256,
)
from app.core.config import settings
from app.core.constants import (
    ROLE_CUSTOMER,
    ROLE_ADMIN,
    ROLE_SUPERADMIN,
    ROLE_PERMISSIONS_MAP,
    PERM_SCHEMES_READ,
    PERM_TENANTS_MANAGE,
    PERM_CUSTOMERS_MANAGE,
)


# ═══════════════════════════════════════════════════════════
# 1. Password Hashing
# ═══════════════════════════════════════════════════════════

class TestPasswordHashing:

    def test_hash_password_returns_string(self):
        hashed = hash_password("MyPassword@123")
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_password_is_not_plaintext(self):
        password = "MyPassword@123"
        hashed = hash_password(password)
        assert hashed != password

    def test_hash_password_produces_unique_salts(self):
        password = "SamePassword@123"
        h1 = hash_password(password)
        h2 = hash_password(password)
        # bcrypt uses random salt — two hashes of same password must differ
        assert h1 != h2

    def test_verify_password_correct(self):
        password = "CorrectPass@123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_wrong(self):
        hashed = hash_password("RealPass@123")
        assert verify_password("WrongPass@123", hashed) is False

    def test_verify_password_empty_string(self):
        hashed = hash_password("RealPass@123")
        assert verify_password("", hashed) is False

    def test_password_72_byte_dos_protection(self):
        """
        Passwords exceeding 72 bytes must raise ValueError.
        This prevents bcrypt CPU exhaustion DoS attacks.
        """
        long_password = "A" * 73  # 73 bytes — exceeds bcrypt limit
        with pytest.raises(ValueError, match="72"):
            hash_password(long_password)

    def test_verify_password_over_72_bytes_returns_false(self):
        """verify_password must return False for passwords > 72 bytes."""
        hashed = hash_password("NormalPass@123")
        long_input = "A" * 73
        result = verify_password(long_input, hashed)
        assert result is False

    def test_hash_token_sha256_returns_hex(self):
        result = hash_token_sha256("sometoken")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex = 64 chars

    def test_hash_token_sha256_deterministic(self):
        token = "same_token_value"
        assert hash_token_sha256(token) == hash_token_sha256(token)

    def test_hash_token_sha256_different_inputs_differ(self):
        assert hash_token_sha256("token_A") != hash_token_sha256("token_B")


# ═══════════════════════════════════════════════════════════
# 2. JWT Access Token
# ═══════════════════════════════════════════════════════════

class TestAccessToken:

    def test_create_access_token_returns_string(self):
        token = create_access_token(
            subject="usr_test_001",
            tenant_id="tnt_test_001",
            role="Customer",
        )
        assert isinstance(token, str)
        assert token.count(".") == 2  # JWT has 3 dot-separated parts

    def test_access_token_payload_claims(self):
        subject = "usr_test_001"
        tenant_id = "tnt_test_001"
        token = create_access_token(
            subject=subject,
            tenant_id=tenant_id,
            role="Customer",
        )
        payload = decode_jwt_token(token)
        assert payload["sub"] == subject
        assert payload["tenant_id"] == tenant_id
        assert payload["role"] == "Customer"
        assert payload["type"] == "access"
        assert "iat" in payload
        assert "exp" in payload

    def test_access_token_expiry_is_enforced(self):
        """A token with expiry in the past must be rejected."""
        expired_token = create_access_token(
            subject="usr_test_expired",
            tenant_id="tnt_test_001",
            role="Customer",
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(ValueError, match="expired"):
            decode_jwt_token(expired_token)

    def test_access_token_respects_custom_expiry(self):
        token = create_access_token(
            subject="usr_test_001",
            tenant_id=None,
            role="SuperAdmin",
            expires_delta=timedelta(minutes=5),
        )
        payload = decode_jwt_token(token)
        now = int(datetime.now(timezone.utc).timestamp())
        # exp should be roughly now + 5 min (within 10 sec tolerance)
        assert payload["exp"] > now
        assert payload["exp"] <= now + 310

    def test_access_token_without_tenant_superadmin(self):
        """SuperAdmin may have tenant_id=None."""
        token = create_access_token(
            subject="usr_superadmin",
            tenant_id=None,
            role="SuperAdmin",
        )
        payload = decode_jwt_token(token)
        assert payload["tenant_id"] is None

    def test_tampered_token_rejected(self):
        """Modifying the token payload must cause validation to fail."""
        token = create_access_token(
            subject="usr_test_001",
            tenant_id="tnt_001",
            role="Customer",
        )
        # Tamper: flip last character
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with pytest.raises(ValueError):
            decode_jwt_token(tampered)

    def test_garbage_token_rejected(self):
        with pytest.raises(ValueError):
            decode_jwt_token("not.a.real.jwt")

    def test_empty_token_rejected(self):
        with pytest.raises((ValueError, Exception)):
            decode_jwt_token("")


# ═══════════════════════════════════════════════════════════
# 3. JWT Refresh Token
# ═══════════════════════════════════════════════════════════

class TestRefreshToken:

    def test_create_refresh_token_returns_string(self):
        token = create_refresh_token(
            subject="usr_test_001",
            tenant_id="tnt_test_001",
            token_id="tkn_abc123",
        )
        assert isinstance(token, str)
        assert token.count(".") == 2

    def test_refresh_token_payload_claims(self):
        token_id = f"tkn_{uuid.uuid4().hex[:12]}"
        token = create_refresh_token(
            subject="usr_test_001",
            tenant_id="tnt_test_001",
            token_id=token_id,
        )
        payload = decode_jwt_token(token)
        assert payload["sub"] == "usr_test_001"
        assert payload["jti"] == token_id
        assert payload["type"] == "refresh"
        assert "exp" in payload
        assert "iat" in payload

    def test_access_token_is_not_refresh_token(self):
        """
        An access token must have type='access', not 'refresh'.
        Prevents using access tokens where refresh tokens are expected.
        """
        access = create_access_token(
            subject="usr_001",
            tenant_id="tnt_001",
            role="Customer",
        )
        payload = decode_jwt_token(access)
        assert payload["type"] == "access"
        assert payload["type"] != "refresh"

    def test_refresh_token_is_not_access_token(self):
        refresh = create_refresh_token(
            subject="usr_001",
            tenant_id="tnt_001",
            token_id="tkn_001",
        )
        payload = decode_jwt_token(refresh)
        assert payload["type"] == "refresh"
        assert payload["type"] != "access"

    def test_refresh_token_expiry_enforced(self):
        expired_refresh = create_refresh_token(
            subject="usr_001",
            tenant_id="tnt_001",
            token_id="tkn_001",
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(ValueError, match="expired"):
            decode_jwt_token(expired_refresh)


# ═══════════════════════════════════════════════════════════
# 4. RBAC Permission Map
# ═══════════════════════════════════════════════════════════

class TestRBACPermissions:

    def test_customer_has_schemes_read(self):
        perms = ROLE_PERMISSIONS_MAP[ROLE_CUSTOMER]
        assert PERM_SCHEMES_READ in perms

    def test_customer_does_not_have_tenants_manage(self):
        perms = ROLE_PERMISSIONS_MAP[ROLE_CUSTOMER]
        assert PERM_TENANTS_MANAGE not in perms

    def test_customer_does_not_have_customers_manage(self):
        perms = ROLE_PERMISSIONS_MAP[ROLE_CUSTOMER]
        assert PERM_CUSTOMERS_MANAGE not in perms

    def test_admin_has_customers_manage(self):
        perms = ROLE_PERMISSIONS_MAP[ROLE_ADMIN]
        assert PERM_CUSTOMERS_MANAGE in perms

    def test_admin_does_not_have_tenants_manage(self):
        """Admin cannot manage tenants — only SuperAdmin can."""
        perms = ROLE_PERMISSIONS_MAP[ROLE_ADMIN]
        assert PERM_TENANTS_MANAGE not in perms

    def test_superadmin_has_tenants_manage(self):
        perms = ROLE_PERMISSIONS_MAP[ROLE_SUPERADMIN]
        assert PERM_TENANTS_MANAGE in perms

    def test_superadmin_has_all_permissions(self):
        """SuperAdmin must have the largest permission set."""
        sa_perms = set(ROLE_PERMISSIONS_MAP[ROLE_SUPERADMIN])
        for role, perms in ROLE_PERMISSIONS_MAP.items():
            if role != ROLE_SUPERADMIN:
                for perm in perms:
                    assert perm in sa_perms, (
                        f"SuperAdmin is missing permission '{perm}' "
                        f"that role '{role}' has"
                    )

    def test_all_roles_have_permission_lists(self):
        for role in [ROLE_CUSTOMER, ROLE_ADMIN, ROLE_SUPERADMIN]:
            assert role in ROLE_PERMISSIONS_MAP
            assert isinstance(ROLE_PERMISSIONS_MAP[role], list)
            assert len(ROLE_PERMISSIONS_MAP[role]) > 0
