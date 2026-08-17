"""Phase 5 — customer-app OTP for sensitive scheme redemption.

Delivery is IN_APP only: the code is written as a Notification the customer's
app reads. No SMS/WhatsApp substitution. The plaintext code never leaves this
service except into that one notification; only a salted hash is persisted.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.auth import User
from app.models.otp import (
    OtpChallenge,
    OTP_PURPOSE_SCHEME_REDEMPTION,
    OTP_TTL_SECONDS,
    OTP_MAX_ATTEMPTS,
)
from app.repositories.otp_repository import OtpRepository
from app.repositories.billing_repository import SaleRepository
from app.repositories.audit_repository import AuditRepository
from app.services.notification_service import NotificationService
from app.exceptions.base import (
    ResourceNotFoundException,
    ForbiddenException,
    ValidationException,
)


def _hash_code(code: str) -> str:
    # Salted with the server secret; short-lived + attempt-limited, so a fast
    # hash is adequate and avoids a bcrypt dependency on a hot path. Compared
    # only with hmac.compare_digest (constant time) at verification.
    return hashlib.sha256(f"{settings.SECRET_KEY}:{code}".encode()).hexdigest()


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


class OtpService:
    @staticmethod
    async def create_redemption_challenge(
        db: AsyncSession, current_user: User, sale_id: str
    ):
        """Issue a redemption OTP for the sale's customer and deliver it IN_APP.
        Returns metadata only (id + expiry) — never the code."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        tenant_id = current_user.tenant_id

        sale = await SaleRepository.get_by_id(db, sale_id, tenant_id)
        if not sale:
            raise ResourceNotFoundException(f"Sale ID '{sale_id}' not found")
        if not sale.customer_id:
            raise ValidationException(
                "This sale has no linked customer, so a redemption OTP cannot be sent."
            )

        # Only the newest code stays valid.
        await OtpRepository.expire_active(
            db, tenant_id, sale.customer_id, OTP_PURPOSE_SCHEME_REDEMPTION, sale_id
        )

        code = _generate_code()
        now = datetime.now(timezone.utc)
        challenge = OtpChallenge(
            id=f"otp_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            customer_id=sale.customer_id,
            purpose=OTP_PURPOSE_SCHEME_REDEMPTION,
            sale_id=sale_id,
            code_hash=_hash_code(code),
            expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
            attempts=0,
            max_attempts=OTP_MAX_ATTEMPTS,
            created_by=current_user.id,
        )
        await OtpRepository.create(db, challenge)

        # Delivery = customer app. The code lives only in this IN_APP notification.
        minutes = OTP_TTL_SECONDS // 60
        await NotificationService.create_notification(
            db,
            tenant_id=tenant_id,
            user_id=sale.customer_id,
            title="Scheme redemption verification code",
            message=(
                f"Your verification code for the scheme redemption on invoice "
                f"{sale.invoice_number} is {code}. It expires in {minutes} minutes. "
                f"Do not share it with anyone."
            ),
            type="SCHEME",
        )

        await AuditRepository.create_log(
            db,
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="OTP_REQUEST",
            target_entity="otp_challenges",
            target_id=challenge.id,
            before_state=None,
            after_state={"purpose": OTP_PURPOSE_SCHEME_REDEMPTION, "sale_id": sale_id},
        )

        await db.commit()
        return {"challenge_id": challenge.id, "expires_at": challenge.expires_at}

    @staticmethod
    async def verify_and_consume(
        db: AsyncSession,
        current_user: User,
        sale_id: str,
        code: str,
        purpose: str = OTP_PURPOSE_SCHEME_REDEMPTION,
    ) -> None:
        """Verify a code and consume it (single use). Commits its own outcome:
        a wrong attempt persists the incremented counter (bounds brute force); a
        correct code persists consumed_at (replay-proof). Raises on any failure.

        Row-locked so two concurrent verifies cannot both succeed on one code.
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        tenant_id = current_user.tenant_id

        sale = await SaleRepository.get_by_id(db, sale_id, tenant_id)
        if not sale or not sale.customer_id:
            raise ResourceNotFoundException(f"Sale ID '{sale_id}' not found")

        challenge = await OtpRepository.get_latest_active_for_update(
            db, tenant_id, sale.customer_id, purpose, sale_id
        )
        if not challenge:
            raise ValidationException("No active verification code. Request a new OTP.")

        now = datetime.now(timezone.utc)
        expires = challenge.expires_at
        if expires.tzinfo is None:  # SQLite returns naive datetimes
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= now:
            raise ValidationException("Verification code has expired. Request a new OTP.")
        if challenge.attempts >= challenge.max_attempts:
            raise ValidationException("Too many incorrect attempts. Request a new OTP.")

        if not hmac.compare_digest(challenge.code_hash, _hash_code(code)):
            challenge.attempts += 1
            await AuditRepository.create_log(
                db, tenant_id=tenant_id, actor_user_id=current_user.id,
                actor_name=current_user.name, actor_role=current_user.role.name,
                action="OTP_VERIFY_FAIL", target_entity="otp_challenges",
                target_id=challenge.id, before_state=None,
                after_state={"attempts": challenge.attempts},
            )
            await db.commit()
            remaining = max(0, challenge.max_attempts - challenge.attempts)
            raise ValidationException(f"Incorrect verification code. {remaining} attempt(s) left.")

        challenge.consumed_at = now
        await AuditRepository.create_log(
            db, tenant_id=tenant_id, actor_user_id=current_user.id,
            actor_name=current_user.name, actor_role=current_user.role.name,
            action="OTP_VERIFY_OK", target_entity="otp_challenges",
            target_id=challenge.id, before_state=None,
            after_state={"sale_id": sale_id},
        )
        await db.commit()
