from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Mirrors TenantPricingService's supported modes exactly — kept as plain
# strings (not a DB enum type) to match this codebase's existing convention
# for status-like fields (see GoldRate/SchemeEnrollment/Payment status
# columns, all plain String).
PRICING_MODE_LIVE_MARKET = "LIVE_MARKET"
PRICING_MODE_LIVE_PLUS_MARKUP = "LIVE_PLUS_MARKUP"
PRICING_MODE_MANUAL_OVERRIDE = "MANUAL_OVERRIDE"

MARKUP_TYPE_PERCENTAGE = "PERCENTAGE"
MARKUP_TYPE_FLAT = "FLAT"


class TenantPricingConfig(Base, TimestampMixin):
    """
    Module 31 / Phase 0 — one row per tenant, defining how that tenant's
    customer-facing selling rate is derived from the platform-wide
    MarketRate. A standing configuration a tenant Admin sets occasionally
    (mode/markup/manual values), never a daily entry — the exact pattern
    this module replaces (see the old per-tenant-per-day gold_rates table,
    left untouched).

    Phase 0 creates this table only. TenantPricingService, which will read
    it, has no implemented logic until Phase 2 — GoldRateService does not
    consult this table yet.
    """
    __tablename__ = "tenant_pricing_config"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PRICING_MODE_LIVE_MARKET, server_default=PRICING_MODE_LIVE_MARKET
    )

    markup_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    markup_gold_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    markup_silver_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)

    manual_gold_24k: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    manual_silver_999: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)

    updated_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
