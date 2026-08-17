from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Phase 5 — one-time verification codes delivered to the CUSTOMER APP (IN_APP
# Notification), never SMS/WhatsApp. Currently only guards sensitive scheme
# redemption; purpose is stored so the same table can gate other actions later.
OTP_PURPOSE_SCHEME_REDEMPTION = "SCHEME_REDEMPTION"
OTP_PURPOSES = [OTP_PURPOSE_SCHEME_REDEMPTION]

OTP_TTL_SECONDS = 300          # 5-minute expiry
OTP_MAX_ATTEMPTS = 5           # wrong-code attempts before the challenge is dead


class OtpChallenge(Base, TimestampMixin):
    """A single expiring, one-time, attempt-limited verification code.

    The plaintext code is NEVER stored — only a salted hash — and the code is
    delivered solely to the customer's app as an IN_APP Notification. A
    challenge is bound to (tenant, customer, purpose, sale) so a code issued for
    one sale can never verify another, and to the customer so it can never be
    consumed on behalf of a different person. consumed_at makes it single-use;
    verification row-locks the row so two concurrent verifies cannot both spend
    the same code (replay/race protection). Append-only history: a superseded
    challenge is expired, not deleted.
    """
    __tablename__ = "otp_challenges"
    __table_args__ = (
        Index("ix_otp_active_lookup", "tenant_id", "customer_id", "purpose", "sale_id"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    # The specific sale this OTP authorises. Bound so a code can only ever
    # release the exact redemption it was requested for.
    sale_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("sales.id", ondelete="CASCADE"), nullable=True, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=OTP_MAX_ATTEMPTS)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
