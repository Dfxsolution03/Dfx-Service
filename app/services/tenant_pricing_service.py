"""
Module 31 / Phase 2 — TenantPricingService.

Resolves a tenant's customer-facing selling rate from TenantPricingConfig +
the latest platform-wide MarketRate, per the tenant's mode (LIVE_MARKET /
LIVE_PLUS_MARKUP / MANUAL_OVERRIDE). Returns None whenever no rate can be
resolved (no config row, no live rate yet, or a misconfigured manual
override) — callers fall back to their existing behavior in that case, so
this service can never turn a previously-working tenant into an error.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_pricing import (
    TenantPricingConfig,
    PRICING_MODE_LIVE_MARKET,
    PRICING_MODE_LIVE_PLUS_MARKUP,
    PRICING_MODE_MANUAL_OVERRIDE,
    MARKUP_TYPE_PERCENTAGE,
    MARKUP_TYPE_FLAT,
)
from app.repositories.market_rate_repository import MarketRateRepository
from app.repositories.tenant_pricing_repository import TenantPricingRepository


@dataclass
class EffectiveRate:
    gold_24k: Decimal
    silver_999: Optional[Decimal]
    source: str
    as_of: datetime


def _apply_markup(base: Optional[Decimal], markup_type: Optional[str], markup_value: Optional[Decimal]) -> Optional[Decimal]:
    if base is None:
        return None
    if markup_value is None:
        return base
    if markup_type == MARKUP_TYPE_PERCENTAGE:
        return base + (base * markup_value / Decimal("100"))
    if markup_type == MARKUP_TYPE_FLAT:
        return base + markup_value
    return base


class TenantPricingService:
    @staticmethod
    async def get_effective_rate(db: AsyncSession, tenant_id: str) -> Optional[EffectiveRate]:
        config: Optional[TenantPricingConfig] = await TenantPricingRepository.get_by_tenant(db, tenant_id)
        if config is None:
            return None

        if config.mode == PRICING_MODE_MANUAL_OVERRIDE:
            if config.manual_gold_24k is None:
                return None
            return EffectiveRate(
                gold_24k=config.manual_gold_24k,
                silver_999=config.manual_silver_999,
                source=PRICING_MODE_MANUAL_OVERRIDE,
                as_of=config.updated_at,
            )

        market = await MarketRateRepository.get_latest(db)
        if market is None:
            return None

        if config.mode == PRICING_MODE_LIVE_PLUS_MARKUP:
            gold = _apply_markup(market.gold_24k, config.markup_type, config.markup_gold_value)
            silver = _apply_markup(market.silver_999, config.markup_type, config.markup_silver_value)
            return EffectiveRate(
                gold_24k=gold,
                silver_999=silver,
                source=PRICING_MODE_LIVE_PLUS_MARKUP,
                as_of=market.fetched_at,
            )

        if config.mode == PRICING_MODE_LIVE_MARKET:
            return EffectiveRate(
                gold_24k=market.gold_24k,
                silver_999=market.silver_999,
                source=PRICING_MODE_LIVE_MARKET,
                as_of=market.fetched_at,
            )

        return None
