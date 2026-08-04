import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_jwt_token,
    hash_token_sha256,
)
from app.core.config import settings
from app.core.constants import ROLE_CUSTOMER
from app.core.logging import logger
from app.exceptions.base import (
    UnauthorizedException,
    ConflictException,
    ResourceNotFoundException,
    ValidationException,
)
from app.models.auth import Tenant, Role, User, RefreshToken, PasswordResetToken, EmailVerificationToken
from app.repositories.audit_repository import AuditRepository
from app.services.token_service import TokenService
from app.services.email_service import get_email_provider
from app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponseData,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    EmailVerificationConfirmRequest,
)


class AuthService:
    @staticmethod
    async def get_public_tenants(db: AsyncSession) -> List[Tenant]:
        """Fetch list of active tenants for public customer store selection."""
        stmt = select(Tenant).where(Tenant.status == "Active").order_by(Tenant.name)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def register_customer(
        db: AsyncSession, req: UserRegisterRequest
    ) -> User:
        """Register a new customer account associated with a selected tenant store."""
        if not req.email and not req.phone:
            raise ValidationException("Either email or phone number must be provided")

        # 1. Verify tenant exists and is Active
        stmt_tenant = select(Tenant).where(Tenant.id == req.tenant_id, Tenant.status == "Active")
        result_tenant = await db.execute(stmt_tenant)
        tenant = result_tenant.scalar_one_or_none()
        if not tenant:
            raise ResourceNotFoundException(f"Selected store ID '{req.tenant_id}' is invalid or inactive")

        # 2. Check for duplicate email or phone
        if req.email:
            stmt_email = select(User).where(User.email == req.email)
            if (await db.execute(stmt_email)).scalar_one_or_none():
                raise ConflictException("An account with this email address already exists")

        if req.phone:
            stmt_phone = select(User).where(User.phone == req.phone)
            if (await db.execute(stmt_phone)).scalar_one_or_none():
                raise ConflictException("An account with this mobile phone number already exists")

        # 3. Get Customer Role
        stmt_role = select(Role).where(Role.name == ROLE_CUSTOMER)
        role = (await db.execute(stmt_role)).scalar_one_or_none()
        if not role:
            raise ResourceNotFoundException("Customer role configuration missing in database")

        # 4. Create User Record
        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        user = User(
            id=user_id,
            tenant_id=req.tenant_id,
            role_id=role.id,
            email=req.email,
            phone=req.phone,
            hashed_password=hash_password(req.password),
            name=req.name,
            kyc_status="Pending",
            member_since=datetime.now(timezone.utc).strftime("%B %Y"),
            is_active=True,
        )
        db.add(user)
        await db.commit()

        # Load role relationship
        stmt_user = select(User).options(joinedload(User.role)).where(User.id == user.id)
        user_loaded = (await db.execute(stmt_user)).scalar_one()

        # Module 18 — best-effort verification email. Mirrors the "a failed
        # revoke must never trap the user in a signed-in shell" resilience
        # pattern already used in logout_user(): an email-send failure must
        # never fail signup itself.
        if user_loaded.email:
            try:
                await AuthService.request_email_verification(db, user_loaded)
            except Exception as e:
                logger.warning(f"Could not send signup verification email to user '{user_loaded.id}': {e}")

        return user_loaded

    @staticmethod
    async def login_user(
        db: AsyncSession, req: UserLoginRequest
    ) -> TokenResponseData:
        """Authenticate user by email or phone and issue JWT Access and Refresh Tokens."""
        username = req.username.strip()

        # Query user by email OR phone
        stmt = (
            select(User)
            .options(joinedload(User.role))
            .where((User.email == username) | (User.phone == username))
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or not verify_password(req.password, user.hashed_password):
            raise UnauthorizedException("Invalid email/phone or password")

        if not user.is_active:
            raise UnauthorizedException("Account is inactive")

        # Generate tokens
        token_id = f"tkn_{uuid.uuid4().hex[:16]}"
        access_token = create_access_token(
            subject=user.id,
            tenant_id=user.tenant_id,
            role=user.role.name,
        )
        refresh_token = create_refresh_token(
            subject=user.id,
            tenant_id=user.tenant_id,
            token_id=token_id,
        )

        # Store hashed refresh token in DB
        refresh_token_entry = RefreshToken(
            id=token_id,
            user_id=user.id,
            token_hash=hash_token_sha256(refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            is_revoked=False,
        )
        db.add(refresh_token_entry)
        await db.commit()

        return TokenResponseData(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @staticmethod
    async def refresh_token_flow(
        db: AsyncSession, refresh_token_str: str
    ) -> TokenResponseData:
        """
        Execute Refresh Token Rotation with Token Theft Mitigation Safeguard.
        """
        try:
            payload = decode_jwt_token(refresh_token_str)
        except ValueError as e:
            raise UnauthorizedException(f"Invalid refresh token: {str(e)}")

        if payload.get("type") != "refresh":
            raise UnauthorizedException("Token provided is not a refresh token")

        user_id = payload.get("sub")

        # Search hashed refresh token in DB
        token_hash = hash_token_sha256(refresh_token_str)
        stmt_tkn = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result_tkn = await db.execute(stmt_tkn)
        db_token = result_tkn.scalar_one_or_none()

        # SECURITY REUSE DETECTION SAFEGUARD:
        # If token was already revoked, a potential breach occurred! Revoke all tokens for user.
        if db_token and db_token.is_revoked:
            logger.warning(
                f"SECURITY REUSE DETECTION ALERT: Revoked refresh token reuse attempted for user '{user_id}'. Revoking all active sessions."
            )
            stmt_revoke_all = update(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.is_revoked == False
            ).values(is_revoked=True)
            await db.execute(stmt_revoke_all)
            await db.commit()
            raise UnauthorizedException("Security alert: Revoked refresh token reused. All sessions invalidated.")

        if not db_token:
            raise UnauthorizedException("Refresh token does not exist")

        if db_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise UnauthorizedException("Refresh token has expired")

        # Fetch user
        stmt_usr = select(User).options(joinedload(User.role)).where(User.id == user_id)
        user = (await db.execute(stmt_usr)).scalar_one_or_none()
        if not user or not user.is_active:
            raise UnauthorizedException("User account associated with refresh token is invalid")

        # 1. Revoke current refresh token
        db_token.is_revoked = True

        # 2. Generate new token pair
        new_token_id = f"tkn_{uuid.uuid4().hex[:16]}"
        new_access_token = create_access_token(
            subject=user.id,
            tenant_id=user.tenant_id,
            role=user.role.name,
        )
        new_refresh_token = create_refresh_token(
            subject=user.id,
            tenant_id=user.tenant_id,
            token_id=new_token_id,
        )

        new_refresh_entry = RefreshToken(
            id=new_token_id,
            user_id=user.id,
            token_hash=hash_token_sha256(new_refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            is_revoked=False,
        )
        db.add(new_refresh_entry)
        await db.commit()

        return TokenResponseData(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="Bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @staticmethod
    async def logout_user(
        db: AsyncSession, user_id: str, refresh_token_str: Optional[str], all_devices: bool
    ) -> None:
        """Revoke user's current refresh token or all active refresh tokens."""
        if all_devices:
            stmt = update(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.is_revoked == False
            ).values(is_revoked=True)
            await db.execute(stmt)
        elif refresh_token_str:
            token_hash = hash_token_sha256(refresh_token_str)
            stmt = update(RefreshToken).where(
                RefreshToken.token_hash == token_hash
            ).values(is_revoked=True)
            await db.execute(stmt)

        await db.commit()

    # ─── Module 18 — Authentication Hardening ───

    @staticmethod
    async def forgot_password(db: AsyncSession, req: ForgotPasswordRequest) -> None:
        """
        Issues a password reset token and emails it, if — and only if — the
        email matches a real, active account. The caller (endpoint) always
        returns the same generic success response regardless of the outcome
        here: this method deliberately never raises/signals whether a match
        was found, so the API can't be used to enumerate registered emails.
        """
        stmt = select(User).options(joinedload(User.role)).where(User.email == req.email)
        user = (await db.execute(stmt)).scalar_one_or_none()

        if not user or not user.is_active:
            return  # Silently no-op — see docstring.

        raw_token = TokenService.generate_raw_token()
        reset_token = PasswordResetToken(
            id=f"prt_{uuid.uuid4().hex[:16]}",
            user_id=user.id,
            token_hash=TokenService.hash_token(raw_token),
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        )
        db.add(reset_token)

        await AuditRepository.create_log(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            actor_name=user.name,
            actor_role=user.role.name if user.role else "Unknown",
            action="PASSWORD_RESET_REQUESTED",
            target_entity="users",
            target_id=user.id,
        )
        await db.commit()

        reset_link = f"{settings.FRONTEND_URL}/auth/reset-password?token={raw_token}"
        try:
            await get_email_provider().send_email(
                to=user.email,
                subject="Reset your DFX Solution password",
                body_text=(
                    f"Hi {user.name},\n\n"
                    f"We received a request to reset your DFX Solution password. This link expires in "
                    f"{settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes and can only be used once:\n\n"
                    f"{reset_link}\n\n"
                    f"If you didn't request this, you can safely ignore this email."
                ),
                body_html=(
                    f"<p>Hi {user.name},</p>"
                    f"<p>We received a request to reset your DFX Solution password. This link expires in "
                    f"{settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes and can only be used once:</p>"
                    f'<p><a href="{reset_link}">{reset_link}</a></p>'
                    f"<p>If you didn't request this, you can safely ignore this email.</p>"
                ),
            )
        except Exception as e:
            # A failed send must never surface as an API error (would leak
            # account existence via error behavior) — logged for ops only.
            logger.warning(f"Could not send password reset email to user '{user.id}': {e}")

    @staticmethod
    async def reset_password(db: AsyncSession, req: ResetPasswordRequest) -> None:
        """Validates a reset token (exists, unexpired, unused) and sets the new
        password. On success: marks the token used, invalidates every other
        outstanding reset token for the user, and revokes every existing
        refresh token (forces re-login on all devices — the same "password
        change invalidates all sessions" practice the reuse-detection
        safeguard in refresh_token_flow already established for a different
        trigger)."""
        token_hash = TokenService.hash_token(req.token)
        stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        reset_token = (await db.execute(stmt)).scalar_one_or_none()

        if not reset_token:
            raise UnauthorizedException("Reset link is invalid")
        if reset_token.used_at is not None:
            raise UnauthorizedException("Reset link has already been used")
        if reset_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise UnauthorizedException("Reset link has expired")

        stmt_user = select(User).options(joinedload(User.role)).where(User.id == reset_token.user_id)
        user = (await db.execute(stmt_user)).scalar_one_or_none()
        if not user or not user.is_active:
            raise UnauthorizedException("Account associated with this reset link is invalid")

        now = datetime.now(timezone.utc)
        user.hashed_password = hash_password(req.new_password)
        reset_token.used_at = now

        # Invalidate every other still-outstanding reset token for this user.
        await db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.id != reset_token.id,
            )
            .values(used_at=now)
        )
        # Revoke every active refresh token — same bulk-revoke pattern used
        # elsewhere in this file — so a password reset actually ends every
        # existing session, not just future login attempts.
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.is_revoked == False)
            .values(is_revoked=True)
        )

        await AuditRepository.create_log(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            actor_name=user.name,
            actor_role=user.role.name if user.role else "Unknown",
            action="PASSWORD_RESET_COMPLETED",
            target_entity="users",
            target_id=user.id,
        )
        await db.commit()

    @staticmethod
    async def request_email_verification(db: AsyncSession, current_user: User) -> None:
        """Issues an email verification token for the current user's own
        registered email and sends it. Unlike forgot_password, this is an
        authenticated action (the caller already knows their own account
        exists), so it's fine to raise a clear error instead of no-op'ing."""
        if not current_user.email:
            raise ValidationException("No email address is on file for this account")
        if current_user.email_verified_at is not None:
            raise ConflictException("Email address is already verified")

        raw_token = TokenService.generate_raw_token()
        verification_token = EmailVerificationToken(
            id=f"evt_{uuid.uuid4().hex[:16]}",
            user_id=current_user.id,
            token_hash=TokenService.hash_token(raw_token),
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS),
        )
        db.add(verification_token)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name if current_user.role else "Unknown",
            action="EMAIL_VERIFICATION_REQUESTED",
            target_entity="users",
            target_id=current_user.id,
        )
        await db.commit()

        verify_link = f"{settings.FRONTEND_URL}/auth/verify-email?token={raw_token}"
        try:
            await get_email_provider().send_email(
                to=current_user.email,
                subject="Verify your DFX Solution email address",
                body_text=(
                    f"Hi {current_user.name},\n\n"
                    f"Please confirm your email address for your DFX Solution account. This link expires in "
                    f"{settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS} hours and can only be used once:\n\n"
                    f"{verify_link}"
                ),
                body_html=(
                    f"<p>Hi {current_user.name},</p>"
                    f"<p>Please confirm your email address for your DFX Solution account. This link expires in "
                    f"{settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS} hours and can only be used once:</p>"
                    f'<p><a href="{verify_link}">{verify_link}</a></p>'
                ),
            )
        except Exception as e:
            logger.warning(f"Could not send verification email to user '{current_user.id}': {e}")

    @staticmethod
    async def confirm_email_verification(db: AsyncSession, req: EmailVerificationConfirmRequest) -> None:
        """Validates a verification token (exists, unexpired, unused) and
        marks the user's email as verified."""
        token_hash = TokenService.hash_token(req.token)
        stmt = select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
        verification_token = (await db.execute(stmt)).scalar_one_or_none()

        if not verification_token:
            raise UnauthorizedException("Verification link is invalid")
        if verification_token.used_at is not None:
            raise UnauthorizedException("Verification link has already been used")
        if verification_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise UnauthorizedException("Verification link has expired")

        stmt_user = select(User).options(joinedload(User.role)).where(User.id == verification_token.user_id)
        user = (await db.execute(stmt_user)).scalar_one_or_none()
        if not user:
            raise UnauthorizedException("Account associated with this verification link no longer exists")

        now = datetime.now(timezone.utc)
        user.email_verified_at = now
        verification_token.used_at = now

        await AuditRepository.create_log(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            actor_name=user.name,
            actor_role=user.role.name if user.role else "Unknown",
            action="EMAIL_VERIFIED",
            target_entity="users",
            target_id=user.id,
        )
        await db.commit()
