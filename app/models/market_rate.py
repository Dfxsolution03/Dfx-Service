from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, Text, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MarketRate(Base, TimestampMixin):
    """
    Module 31 / Phase 0 — platform-wide live market rate snapshots.

    Not tenant-scoped: the gold/silver market price itself doesn't vary by
    tenant, only a tenant's customer-facing selling rate does (see
    TenantPricingConfig, which derives from this table but is never mixed
    into it). One row per successful provider fetch — this table is an
    append-only historical log, never overwritten on update.

    raw_payload / provider_metadata are JSON-encoded Text (matching this
    codebase's existing AuditLog.before_state/after_state convention, not a
    native JSONB column) — provider_metadata is where provider-specific
    extras land (e.g. additional purities, AM/PM fix labels), so onboarding
    a new provider never requires a schema migration.

    Phase 0 creates this table only. Nothing writes to it yet —
    MarketRateSyncService.sync() is unimplemented until Phase 1.
    """
    __tablename__ = "market_rates"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    gold_24k: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    silver_999: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR", server_default="INR")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="PER_GRAM", server_default="PER_GRAM")

    raw_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # SET NULL (not CASCADE, unlike most FKs in this codebase) — this column
    # is an audit reference on an append-only historical log; deleting the
    # admin user who once performed an override must not delete historical
    # price rows.
    overridden_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    override_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    fetch_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
