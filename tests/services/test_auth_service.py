"""
JROS Service Tests — AuthService
==================================

Tests AuthService static methods directly using a real AsyncSession
against Supabase PostgreSQL (no HTTP layer involved).

Covers:
  - get_public_tenants
  - register_customer (happy path + duplicate + invalid tenant)
  - login_user (by email + by phone + wrong creds)
  - refresh_token_flow (rotation + reuse detection)
  - logout_user (single device + all devices)
"""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.auth import Tenant, User, RefreshToken
from app.services.token_service import TokenService
from app.core.security import hash_token_sha256
from app.schemas.auth import UserRegisterRequest, UserLoginRequest
from app.services.auth_service import AuthService
from app.exceptions.base import (
    ConflictException,
    ResourceNotFoundException,
    UnauthorizedException,
    ValidationException,
)
from tests.conftest import unique_email, unique_phone


# ═══════════════════════════════════════════════════════════
# 1. get_public_tenants
# ═══════════════════════════════════════════════════════════

class TestGetPublicTenants:

    async def test_returns_list(self, db_session: AsyncSession, test_tenant: Tenant):
        result = await AuthService.get_public_tenants(db_session)
        assert isinstance(result, list)

    async def test_active_tenants_included(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        tenants = await AuthService.get_public_tenants(db_session)
        ids = [t.id for t in tenants]
        assert test_tenant.id in ids

    async def test_all_returned_tenants_are_active(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        tenants = await AuthService.get_public_tenants(db_session)
        for t in tenants:
            assert t.status == "Active", f"Non-active tenant in public list: {t.id}"


# ═══════════════════════════════════════════════════════════
# 2. register_customer
# ═══════════════════════════════════════════════════════════

class TestRegisterCustomer:

    async def test_successful_registration(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        req = UserRegisterRequest(
            name="Priya Sharma",
            email=unique_email(),
            password="TestPass@123",
            tenant_id=test_tenant.id,
        )
        user = await AuthService.register_customer(db_session, req)
        assert user is not None
        assert user.name == "Priya Sharma"
        assert user.kyc_status == "Pending"
        assert user.is_active is True
        assert user.tenant_id == test_tenant.id

    async def test_registration_hashes_password(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        password = "PlainPass@123"
        req = UserRegisterRequest(
            name="Test User",
            email=unique_email(),
            password=password,
            tenant_id=test_tenant.id,
        )
        user = await AuthService.register_customer(db_session, req)
        assert user.hashed_password != password
        assert len(user.hashed_password) > 20

    async def test_duplicate_email_raises_conflict(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        email = unique_email()
        req = UserRegisterRequest(
            name="Duplicate User",
            email=email,
            password="TestPass@123",
            tenant_id=test_tenant.id,
        )
        await AuthService.register_customer(db_session, req)
        with pytest.raises(ConflictException):
            await AuthService.register_customer(db_session, req)

    async def test_invalid_tenant_raises_not_found(
        self, db_session: AsyncSession
    ):
        req = UserRegisterRequest(
            name="Invalid Tenant User",
            email=unique_email(),
            password="TestPass@123",
            tenant_id="tnt_does_not_exist_99",
        )
        with pytest.raises(ResourceNotFoundException):
            await AuthService.register_customer(db_session, req)

    async def test_registration_with_phone(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        req = UserRegisterRequest(
            name="Phone User",
            phone=unique_phone(),
            password="TestPass@123",
            tenant_id=test_tenant.id,
        )
        user = await AuthService.register_customer(db_session, req)
        assert user.phone is not None

    async def test_registration_assigns_customer_role(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        req = UserRegisterRequest(
            name="Role Check User",
            email=unique_email(),
            password="TestPass@123",
            tenant_id=test_tenant.id,
        )
        user = await AuthService.register_customer(db_session, req)
        assert user.role.name == "Customer"


# ═══════════════════════════════════════════════════════════
# 3. login_user
# ═══════════════════════════════════════════════════════════

class TestLoginUser:

    async def _register(
        self, db: AsyncSession, tenant: Tenant, email: str, password: str = "Pass@123"
    ) -> User:
        req = UserRegisterRequest(
            name="Login Test User",
            email=email,
            password=password,
            tenant_id=tenant.id,
        )
        return await AuthService.register_customer(db, req)

    async def test_login_returns_tokens(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        email = unique_email()
        await self._register(db_session, test_tenant, email)
        result = await AuthService.login_user(
            db_session, UserLoginRequest(username=email, password="Pass@123")
        )
        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "Bearer"
        assert result.expires_in > 0

    async def test_login_wrong_password_raises_unauthorized(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        email = unique_email()
        await self._register(db_session, test_tenant, email)
        with pytest.raises(UnauthorizedException):
            await AuthService.login_user(
                db_session,
                UserLoginRequest(username=email, password="WrongPass@999")
            )

    async def test_login_nonexistent_user_raises_unauthorized(
        self, db_session: AsyncSession
    ):
        with pytest.raises(UnauthorizedException):
            await AuthService.login_user(
                db_session,
                UserLoginRequest(username="ghost@nobody.com", password="AnyPass@123")
            )

    async def test_login_stores_hashed_refresh_token(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        email = unique_email()
        await self._register(db_session, test_tenant, email)
        tokens = await AuthService.login_user(
            db_session, UserLoginRequest(username=email, password="Pass@123")
        )
        # Verify refresh token was persisted in DB
        from app.core.security import hash_token_sha256
        token_hash = hash_token_sha256(tokens.refresh_token)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        db_token = (await db_session.execute(stmt)).scalar_one_or_none()
        assert db_token is not None
        assert db_token.is_revoked is False


# ═══════════════════════════════════════════════════════════
# 4. refresh_token_flow
# ═══════════════════════════════════════════════════════════

class TestRefreshTokenFlow:

    async def _login(
        self, db: AsyncSession, tenant: Tenant
    ) -> dict:
        email = unique_email()
        req = UserRegisterRequest(
            name="Refresh Test",
            email=email,
            password="RefPass@123",
            tenant_id=tenant.id,
        )
        await AuthService.register_customer(db, req)
        tokens = await AuthService.login_user(
            db, UserLoginRequest(username=email, password="RefPass@123")
        )
        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
        }

    async def test_refresh_returns_new_pair(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        tokens = await self._login(db_session, test_tenant)
        result = await AuthService.refresh_token_flow(
            db_session, tokens["refresh_token"]
        )
        assert result.access_token
        assert result.refresh_token
        assert result.refresh_token != tokens["refresh_token"]

    async def test_old_refresh_token_revoked_after_rotation(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        tokens = await self._login(db_session, test_tenant)
        old_refresh = tokens["refresh_token"]

        # Rotate
        await AuthService.refresh_token_flow(db_session, old_refresh)

        # Reuse old refresh — should raise security error
        with pytest.raises(UnauthorizedException):
            await AuthService.refresh_token_flow(db_session, old_refresh)

    async def test_invalid_refresh_token_raises_unauthorized(
        self, db_session: AsyncSession
    ):
        with pytest.raises(UnauthorizedException):
            await AuthService.refresh_token_flow(db_session, "fake.refresh.token")


# ═══════════════════════════════════════════════════════════
# 5. logout_user
# ═══════════════════════════════════════════════════════════

class TestLogoutUser:

    async def _login(
        self, db: AsyncSession, tenant: Tenant
    ) -> tuple:
        email = unique_email()
        req = UserRegisterRequest(
            name="Logout Test",
            email=email,
            password="LogPass@123",
            tenant_id=tenant.id,
        )
        user = await AuthService.register_customer(db, req)
        tokens = await AuthService.login_user(
            db, UserLoginRequest(username=email, password="LogPass@123")
        )
        return user, tokens

    async def test_logout_single_device_revokes_token(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        user, tokens = await self._login(db_session, test_tenant)
        await AuthService.logout_user(
            db_session,
            user_id=user.id,
            refresh_token_str=tokens.refresh_token,
            all_devices=False,
        )
        # After logout, the refresh token must be revoked
        from app.core.security import hash_token_sha256
        token_hash = hash_token_sha256(tokens.refresh_token)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        db_token = (await db_session.execute(stmt)).scalar_one_or_none()
        assert db_token is not None
        assert db_token.is_revoked is True

    async def test_logout_all_devices_revokes_all_tokens(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        user, tokens1 = await self._login(db_session, test_tenant)
        # Login again to get a second token
        tokens2 = await AuthService.login_user(
            db_session,
            UserLoginRequest(
                username=user.email,
                password="LogPass@123",
            )
        )
        await AuthService.logout_user(
            db_session,
            user_id=user.id,
            refresh_token_str=None,
            all_devices=True,
        )
        # All active tokens for this user must be revoked
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.is_revoked == False,
        )
        active = (await db_session.execute(stmt)).scalars().all()
        assert len(active) == 0, "All sessions were not revoked"


# ═══════════════════════════════════════════════════════════
# Module 18 — Authentication Hardening
# ═══════════════════════════════════════════════════════════

from app.models.auth import PasswordResetToken, EmailVerificationToken
from app.schemas.auth import ForgotPasswordRequest, ResetPasswordRequest, EmailVerificationConfirmRequest
from app.core.security import verify_password  # hash_token_sha256 already imported above


class TestForgotPassword:

    async def test_creates_token_for_real_user(self, db_session: AsyncSession, customer_user: User):
        await AuthService.forgot_password(db_session, ForgotPasswordRequest(email=customer_user.email))
        stmt = select(PasswordResetToken).where(PasswordResetToken.user_id == customer_user.id)
        tokens = (await db_session.execute(stmt)).scalars().all()
        assert len(tokens) == 1
        assert tokens[0].used_at is None

    async def test_silently_no_ops_for_unknown_email(self, db_session: AsyncSession):
        # Must not raise — prevents account-enumeration via error behavior.
        await AuthService.forgot_password(
            db_session, ForgotPasswordRequest(email="definitely-not-registered@example.com")
        )

    async def test_silently_no_ops_for_inactive_user(self, db_session: AsyncSession, customer_user: User):
        customer_user.is_active = False
        await db_session.commit()
        await AuthService.forgot_password(db_session, ForgotPasswordRequest(email=customer_user.email))
        stmt = select(PasswordResetToken).where(PasswordResetToken.user_id == customer_user.id)
        tokens = (await db_session.execute(stmt)).scalars().all()
        assert len(tokens) == 0


class TestResetPassword:

    async def _issue_token(self, db_session: AsyncSession, user: User) -> str:
        raw = TokenService.generate_raw_token()
        db_session.add(
            PasswordResetToken(
                id=f"prt_test_{uuid.uuid4().hex[:12]}",
                user_id=user.id,
                token_hash=TokenService.hash_token(raw),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        await db_session.commit()
        return raw

    async def test_happy_path_changes_password(self, db_session: AsyncSession, customer_user: User):
        raw = await self._issue_token(db_session, customer_user)
        await AuthService.reset_password(
            db_session, ResetPasswordRequest(token=raw, new_password="BrandNewPass@456")
        )
        stmt = select(User).where(User.id == customer_user.id)
        refreshed = (await db_session.execute(stmt)).scalar_one()
        assert verify_password("BrandNewPass@456", refreshed.hashed_password)

    async def test_marks_token_used(self, db_session: AsyncSession, customer_user: User):
        raw = await self._issue_token(db_session, customer_user)
        await AuthService.reset_password(
            db_session, ResetPasswordRequest(token=raw, new_password="BrandNewPass@456")
        )
        token_hash = TokenService.hash_token(raw)
        stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        db_token = (await db_session.execute(stmt)).scalar_one()
        assert db_token.used_at is not None

    async def test_rejects_reuse_of_already_used_token(self, db_session: AsyncSession, customer_user: User):
        raw = await self._issue_token(db_session, customer_user)
        await AuthService.reset_password(db_session, ResetPasswordRequest(token=raw, new_password="First@12345"))
        with pytest.raises(UnauthorizedException):
            await AuthService.reset_password(db_session, ResetPasswordRequest(token=raw, new_password="Second@6789"))

    async def test_rejects_expired_token(self, db_session: AsyncSession, customer_user: User):
        raw = TokenService.generate_raw_token()
        db_session.add(
            PasswordResetToken(
                id=f"prt_test_{uuid.uuid4().hex[:12]}",
                user_id=customer_user.id,
                token_hash=TokenService.hash_token(raw),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # already expired
            )
        )
        await db_session.commit()
        with pytest.raises(UnauthorizedException):
            await AuthService.reset_password(db_session, ResetPasswordRequest(token=raw, new_password="Whatever@123"))

    async def test_rejects_unknown_token(self, db_session: AsyncSession):
        with pytest.raises(UnauthorizedException):
            await AuthService.reset_password(
                db_session, ResetPasswordRequest(token="not-a-real-token", new_password="Whatever@123")
            )

    async def test_invalidates_other_outstanding_tokens_for_same_user(
        self, db_session: AsyncSession, customer_user: User
    ):
        raw1 = await self._issue_token(db_session, customer_user)
        raw2 = await self._issue_token(db_session, customer_user)
        await AuthService.reset_password(db_session, ResetPasswordRequest(token=raw1, new_password="First@12345"))
        # raw2 must now be rejected too, even though it was never itself submitted.
        with pytest.raises(UnauthorizedException):
            await AuthService.reset_password(db_session, ResetPasswordRequest(token=raw2, new_password="Second@6789"))

    async def test_revokes_all_existing_refresh_tokens(self, db_session: AsyncSession, customer_user: User):
        login = await AuthService.login_user(
            db_session, UserLoginRequest(username=customer_user.email, password="TestPass@123")
        )
        raw = await self._issue_token(db_session, customer_user)
        await AuthService.reset_password(db_session, ResetPasswordRequest(token=raw, new_password="BrandNewPass@456"))

        token_hash = hash_token_sha256(login.refresh_token)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        db_token = (await db_session.execute(stmt)).scalar_one()
        assert db_token.is_revoked is True


class TestRequestEmailVerification:

    async def test_creates_token_for_user_with_email(self, db_session: AsyncSession, customer_user: User):
        await AuthService.request_email_verification(db_session, customer_user)
        stmt = select(EmailVerificationToken).where(EmailVerificationToken.user_id == customer_user.id)
        tokens = (await db_session.execute(stmt)).scalars().all()
        assert len(tokens) == 1

    async def test_rejects_user_with_no_email(self, db_session: AsyncSession, customer_user: User):
        customer_user.email = None
        await db_session.commit()
        with pytest.raises(ValidationException):
            await AuthService.request_email_verification(db_session, customer_user)

    async def test_rejects_already_verified_email(self, db_session: AsyncSession, customer_user: User):
        customer_user.email_verified_at = datetime.now(timezone.utc)
        await db_session.commit()
        with pytest.raises(ConflictException):
            await AuthService.request_email_verification(db_session, customer_user)


class TestConfirmEmailVerification:

    async def _issue_token(self, db_session: AsyncSession, user: User) -> str:
        raw = TokenService.generate_raw_token()
        db_session.add(
            EmailVerificationToken(
                id=f"evt_test_{uuid.uuid4().hex[:12]}",
                user_id=user.id,
                token_hash=TokenService.hash_token(raw),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        await db_session.commit()
        return raw

    async def test_happy_path_sets_email_verified_at(self, db_session: AsyncSession, customer_user: User):
        raw = await self._issue_token(db_session, customer_user)
        await AuthService.confirm_email_verification(db_session, EmailVerificationConfirmRequest(token=raw))
        stmt = select(User).where(User.id == customer_user.id)
        refreshed = (await db_session.execute(stmt)).scalar_one()
        assert refreshed.email_verified_at is not None

    async def test_rejects_reuse(self, db_session: AsyncSession, customer_user: User):
        raw = await self._issue_token(db_session, customer_user)
        await AuthService.confirm_email_verification(db_session, EmailVerificationConfirmRequest(token=raw))
        with pytest.raises(UnauthorizedException):
            await AuthService.confirm_email_verification(db_session, EmailVerificationConfirmRequest(token=raw))

    async def test_rejects_expired_token(self, db_session: AsyncSession, customer_user: User):
        raw = TokenService.generate_raw_token()
        db_session.add(
            EmailVerificationToken(
                id=f"evt_test_{uuid.uuid4().hex[:12]}",
                user_id=customer_user.id,
                token_hash=TokenService.hash_token(raw),
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        await db_session.commit()
        with pytest.raises(UnauthorizedException):
            await AuthService.confirm_email_verification(db_session, EmailVerificationConfirmRequest(token=raw))

    async def test_rejects_unknown_token(self, db_session: AsyncSession):
        with pytest.raises(UnauthorizedException):
            await AuthService.confirm_email_verification(
                db_session, EmailVerificationConfirmRequest(token="not-a-real-token")
            )


class TestSignupTriggersVerificationEmail:

    async def test_signup_creates_verification_token(self, db_session: AsyncSession, test_tenant: Tenant):
        email = unique_email()
        req = UserRegisterRequest(
            name="Verify Me",
            email=email,
            phone=unique_phone(),
            password="SignupPass@123",
            tenant_id=test_tenant.id,
        )
        user = await AuthService.register_customer(db_session, req)
        stmt = select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
        tokens = (await db_session.execute(stmt)).scalars().all()
        assert len(tokens) == 1
