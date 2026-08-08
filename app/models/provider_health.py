from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

STATUS_UNKNOWN = "UNKNOWN"
STATUS_HEALTHY = "HEALTHY"
STATUS_DEGRADED = "DEGRADED"
STATUS_DOWN = "DOWN"


class ProviderHealth(Base, TimestampMixin):
    """
    Module 31 / Phase 0 — one row per known market-rate provider, holding
    current sync health (not history — see MarketRate for the append-only
    historical feed; this table is small and mutable, upserted in place).

    Will be updated by MarketRateSyncService.sync() after every attempt,
    success or failure, and surfaced to Super Admin plus reused by future
    failure alerting — one source of truth for provider status.

    Phase 0 creates this table only. Nothing writes to it yet.
    """
    __tablename__ = "provider_health"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)

    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_UNKNOWN, server_default=STATUS_UNKNOWN)
