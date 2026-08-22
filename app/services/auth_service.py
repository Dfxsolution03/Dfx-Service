import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
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
from app.models.auth import Tenant, Subscription, Role, User, RefreshToken, PasswordResetToken, EmailVerificationToken
from app.repositories.audit_repository import AuditRepository
from app.repositories.customer_repository import CustomerRepository
from app.services.google_identity_service import GoogleIdentity, verify_google_id_token
from app.services.token_service import TokenService
from app.services.email_service import get_email_provider
from app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    GoogleLoginRequest,
    TokenResponseData,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    EmailVerificationConfirmRequest,
)


async def _enforce_tenant_access(db: AsyncSession, tenant_id: str) -> None:
    """
    Real backend enforcement of tenant access lifecycle (Trial/Indefinite/
    Suspended) — called on every login and token refresh for a non-SuperAdmin
    user, so a suspended tenant or an expired trial actually blocks access
    rather than just being a display flag the frontend could ignore.

    A tenant with no Subscription row (shouldn't happen for anything
    provisioned via SuperAdminService, but is possible for older/seed data)
    is treated as indefinite — absence of a subscription is not itself a
    reason to lock someone out.
    """
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant:
        raise UnauthorizedException("Tenant account no longer exists")

    subscription = (
        await db.execute(select(Subscription).where(Subscription.tenant_id == tenant_id))
    ).scalar_one_or_none()

    # Lazily flip an expired trial to Expired/Inactive right here — the only
    # trigger point that matters is "someone tried to use this tenant",
    # since there is no background scheduler in this codebase.
    if (
        subscription
        and subscription.trial_ends_at is not None
        and subscription.trial_ends_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)
        and subscription.status not in ("Expired", "Suspended")
    ):
        subscription.status = "Expired"
        tenant.status = "Inactive"
        await AuditRepository.create_log(
            db, tenant_id=tenant.id, actor_user_id="system", actor_name="System",
            actor_role="System", action="SUBSCRIPTION_AUTO_EXPIRE",
            target_entity="subscriptions", target_id=subscription.id,
            before_state={"status": "Trial"}, after_state={"status": "Expired"},
        )
        await db.commit()

    if tenant.status != "Active":
        if subscription and subscription.status == "Expired":
            raise UnauthorizedException("This store's trial period has expired. Contact your platform administrator.")
        raise UnauthorizedException("This store's access has been suspended. Contact your platform administrator.")


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
        # The customer code is reserved inside this same transaction — if the
        # insert below fails, the reservation rolls back with it. It is never
        # taken from the request: staff and customers cannot choose a code.
        try:
            customer_code = await CustomerRepository.allocate_customer_code(db, req.tenant_id)
        except Exception as e:
            logger.warning(f"Could not allocate sequential customer code: {e}")
            customer_code = f"DFX-CUST-{uuid.uuid4().hex[:6].upper()}"
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
            customer_code=customer_code,
            member_since=datetime.now(timezone.utc).strftime("%B %Y"),
            is_active=True,
        )
        if req.date_of_birth and hasattr(user, "date_of_birth"):
            try:
                setattr(user, "date_of_birth", req.date_of_birth)
            except Exception:
                pass
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
            .order_by(User.created_at.desc())
        )
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user or not verify_password(req.password, user.hashed_password):
            raise UnauthorizedException("Invalid email/phone or password")

        if not user.is_active:
            raise UnauthorizedException("Account is inactive")

        if user.tenant_id:
            await _enforce_tenant_access(db, user.tenant_id)

        return await AuthService._issue_token_pair(db, user)

    @staticmethod
    async def google_login(
        db: AsyncSession, req: GoogleLoginRequest
    ) -> TokenResponseData:
        """
        Authenticate (or, for a first-time Google user, register) via a Google
        OAuth ID token.

        The identity is taken *entirely* from the verified token claims — the
        request body contributes nothing but the raw token and the chosen
        store. Once the Google account has been mapped onto a User row this is
        the same login as any other: identical tenant-lifecycle enforcement
        and identical token issuance, through the same helpers login_user uses.
        """
        identity = await verify_google_id_token(req.id_token)

        user = await AuthService._find_user_for_google_identity(db, identity)

        if user is None:
            # First time this Google account has been seen. Registering it
            # needs a store, and picking one on the user's behalf is not this
            # function's call to make — an arbitrary tenant would silently bind
            # a customer to a jewellery store they never chose. The client
            # detects this specific error (errors[0].field == "tenant_id") and
            # re-prompts with the store picker.
            if not req.tenant_id:
                raise ValidationException(
                    "Select your jewellery store to finish signing in with Google.",
                    field="tenant_id",
                )
            user = await AuthService._register_google_customer(db, identity, req.tenant_id)

        if not user.is_active:
            raise UnauthorizedException("Account is inactive")

        # The tenant enforced is always the one on the user's own row, never
        # the tenant_id the client sent — an existing customer of store A
        # cannot be moved into store B by passing a different id.
        if user.tenant_id:
            await _enforce_tenant_access(db, user.tenant_id)

        return await AuthService._issue_token_pair(db, user, device_info="Google Sign-In")

    @staticmethod
    async def _find_user_for_google_identity(
        db: AsyncSession, identity: GoogleIdentity
    ) -> Optional[User]:
        """
        Resolve a verified Google account to an existing user, in priority
        order:

          1. `google_sub` — Google's stable account id. Authoritative: it
             survives the user changing their Gmail address.
          2. Verified email, matched case-insensitively (older rows hold
             whatever casing was typed at signup). This is what links Google
             sign-in onto an account originally created with email+password
             instead of creating a second one. Safe precisely because the
             email came out of a verified token.

        A match found by email is back-filled with `google_sub`, so subsequent
        sign-ins take path 1.
        """
        by_sub = (
            await db.execute(
                select(User)
                .options(joinedload(User.role))
                .where(User.google_sub == identity.subject)
            )
        ).scalar_one_or_none()
        if by_sub:
            return by_sub

        by_email = (
            await db.execute(
                select(User)
                .options(joinedload(User.role))
                .where(func.lower(User.email) == identity.email)
                .order_by(User.created_at)
            )
        ).scalars().first()

        if by_email and not by_email.google_sub:
            by_email.google_sub = identity.subject
            # Google has already vouched for this address, so an account that
            # never managed to complete email verification (no SMTP provider
            # configured, link expired, ...) becomes verified here.
            if by_email.email_verified_at is None:
                by_email.email_verified_at = datetime.now(timezone.utc)
            await db.commit()
            # Deliberately no db.refresh(): the two fields just written are
            # already correct in memory (the session factory uses
            # expire_on_commit=False), and refreshing would expire the
            # joinedload-ed `role` — which the caller reads to mint the access
            # token, and which cannot be lazy-loaded on an async session.

        return by_email

    @staticmethod
    async def _register_google_customer(
        db: AsyncSession, identity: GoogleIdentity, tenant_id: str
    ) -> User:
        """
        Create a Customer for a first-time Google account, following the same
        rules as register_customer: the store must exist and be Active, the
        Customer role must be seeded, and the customer code is allocated by the
        backend inside this transaction.
        """
        tenant = (
            await db.execute(
                select(Tenant).where(Tenant.id == tenant_id, Tenant.status == "Active")
            )
        ).scalar_one_or_none()
        if not tenant:
            raise ValidationException(
                f"Selected store ID '{tenant_id}' is invalid or inactive",
                field="tenant_id",
            )

        role = (
            await db.execute(select(Role).where(Role.name == ROLE_CUSTOMER))
        ).scalar_one_or_none()
        if not role:
            raise ResourceNotFoundException("Customer role configuration missing in database")

        customer_code = await CustomerRepository.allocate_customer_code(db, tenant_id)
        user = User(
            id=f"usr_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            role_id=role.id,
            email=identity.email,
            google_sub=identity.subject,
            # Google accounts have no password in this system. A random,
            # discarded secret keeps the NOT NULL column honest while
            # guaranteeing no password can ever authenticate this row — the
            # plaintext is never stored, logged or returned, so there is
            # nothing to verify against. Such a user signs in with Google, or
            # sets a password for the first time via "forgot password".
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            name=(identity.name or identity.email.split("@")[0]),
            avatar_url=identity.picture,
            kyc_status="Pending",
            customer_code=customer_code,
            member_since=datetime.now(timezone.utc).strftime("%B %Y"),
            # Google only ever hands us an address it has verified (see
            # verify_google_id_token), so this account starts out verified
            # rather than being emailed a link it does not need.
            email_verified_at=datetime.now(timezone.utc),
            is_active=True,
        )
        db.add(user)

        try:
            await db.commit()
        except IntegrityError:
            # Two taps of the Google button racing each other: the loser hits
            # the unique index on google_sub (or the tenant/customer_code
            # constraint) and simply adopts the row the winner created.
            await db.rollback()
            existing = (
                await db.execute(
                    select(User)
                    .options(joinedload(User.role))
                    .where(User.google_sub == identity.subject)
                )
            ).scalar_one_or_none()
            if existing is None:
                raise ConflictException(
                    "Could not complete Google sign-in. Please try again."
                )
            return existing

        return (
            await db.execute(
                select(User).options(joinedload(User.role)).where(User.id == user.id)
            )
        ).scalar_one()

    @staticmethod
    async def _issue_token_pair(
        db: AsyncSession, user: User, device_info: Optional[str] = None
    ) -> TokenResponseData:
        """
        Mint an access/refresh pair and persist the refresh token's hash.
        Extracted from login_user so Google sign-in issues *identical*
        credentials through the same code path rather than a parallel one —
        refresh-token rotation and theft detection then work for a
        Google-authenticated session exactly as they do for a password one.
        """
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

        db.add(
            RefreshToken(
                id=token_id,
                user_id=user.id,
                token_hash=hash_token_sha256(refresh_token),
                expires_at=datetime.now(timezone.utc)
                + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                is_revoked=False,
                device_info=device_info,
            )
        )
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

        if user.tenant_id:
            await _enforce_tenant_access(db, user.tenant_id)

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
