from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Text, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PlatformIntegration(Base, TimestampMixin):
    """
    SuperAdmin-controlled enabled/disabled toggle + last connection-test
    result for a provider. Never stores a credential — those live in env
    vars (see app/core/integration_registry.py). One row per provider key
    from PROVIDER_REGISTRY, created lazily on first access.
    """
    __tablename__ = "platform_integrations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'success' | 'failed'
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Webhook(Base, TimestampMixin):
    """
    Outbound webhook configuration foundation (SuperAdmin-managed, platform
    level). Delivery engine/retry execution is intentionally not built yet —
    only the configuration contract the spec asked for. secret_hash never
    stores the raw signing secret; it is shown once at creation/rotation and
    never again (same "reveal once" pattern as an API key).
    """
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_delivery_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
