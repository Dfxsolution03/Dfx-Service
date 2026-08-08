"""Module 31 / Phase 2 — TenantPricingService.get_effective_rate() tests."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.models.market_rate import MarketRate
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
from app.services.tenant_pricing_service import TenantPricingService

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _cleanup(db_session):
    # MarketRate is platform-wide (not tenant-scoped) and committed directly
    # by these tests — it must not leak into other tests via get_latest().
    yield
    await db_session.execute(delete(MarketRate).where(MarketRate.provider == "METALPRICEAPI"))
    await db_session.execute(delete(TenantPricingConfig))
    await db_session.commit()


async def _seed_market_rate(db, gold=Decimal("9800.0000"), silver=Decimal("118.0000")):
    market = MarketRate(
        id=f"mkr_{uuid.uuid4().hex[:12]}",
        provider="METALPRICEAPI",
        gold_24k=gold,
        silver_999=silver,
        currency="INR",
        unit="PER_GRAM",
        fetched_at=datetime.now(timezone.utc),
    )
    await MarketRateRepository.create(db, market)
    await db.commit()
    return market


async def _seed_config(db, tenant_id, **kwargs):
    config = TenantPricingConfig(id=f"tpc_{uuid.uuid4().hex[:12]}", tenant_id=tenant_id, **kwargs)
    await TenantPricingRepository.create(db, config)
    await db.commit()
    await db.refresh(config)
    return config


async def test_no_config_returns_none(db_session, test_tenant):
    result = await TenantPricingService.get_effective_rate(db_session, test_tenant.id)
    assert result is None


async def test_live_market_mode_mirrors_latest_market_rate(db_session, test_tenant):
    await _seed_market_rate(db_session)
    await _seed_config(db_session, test_tenant.id, mode=PRICING_MODE_LIVE_MARKET)

    result = await TenantPricingService.get_effective_rate(db_session, test_tenant.id)
    assert result is not None
    assert result.gold_24k == Decimal("9800.0000")
    assert result.silver_999 == Decimal("118.0000")
    assert result.source == PRICING_MODE_LIVE_MARKET


async def test_live_market_mode_with_no_market_rate_returns_none(db_session, test_tenant):
    await _seed_config(db_session, test_tenant.id, mode=PRICING_MODE_LIVE_MARKET)
    result = await TenantPricingService.get_effective_rate(db_session, test_tenant.id)
    assert result is None


async def test_live_plus_markup_percentage(db_session, test_tenant):
    await _seed_market_rate(db_session, gold=Decimal("10000.0000"), silver=Decimal("100.0000"))
    await _seed_config(
        db_session,
        test_tenant.id,
        mode=PRICING_MODE_LIVE_PLUS_MARKUP,
        markup_type=MARKUP_TYPE_PERCENTAGE,
        markup_gold_value=Decimal("5"),
        markup_silver_value=Decimal("10"),
    )

    result = await TenantPricingService.get_effective_rate(db_session, test_tenant.id)
    assert result.gold_24k == Decimal("10500.0000")
    assert result.silver_999 == Decimal("110.0000")
    assert result.source == PRICING_MODE_LIVE_PLUS_MARKUP


async def test_live_plus_markup_flat(db_session, test_tenant):
    await _seed_market_rate(db_session, gold=Decimal("10000.0000"), silver=Decimal("100.0000"))
    await _seed_config(
        db_session,
        test_tenant.id,
        mode=PRICING_MODE_LIVE_PLUS_MARKUP,
        markup_type=MARKUP_TYPE_FLAT,
        markup_gold_value=Decimal("50"),
        markup_silver_value=Decimal("2"),
    )

    result = await TenantPricingService.get_effective_rate(db_session, test_tenant.id)
    assert result.gold_24k == Decimal("10050.0000")
    assert result.silver_999 == Decimal("102.0000")


async def test_manual_override_mode(db_session, test_tenant):
    await _seed_config(
        db_session,
        test_tenant.id,
        mode=PRICING_MODE_MANUAL_OVERRIDE,
        manual_gold_24k=Decimal("9999.0000"),
        manual_silver_999=Decimal("120.0000"),
    )
    result = await TenantPricingService.get_effective_rate(db_session, test_tenant.id)
    assert result.gold_24k == Decimal("9999.0000")
    assert result.silver_999 == Decimal("120.0000")
    assert result.source == PRICING_MODE_MANUAL_OVERRIDE


async def test_manual_override_mode_without_value_returns_none(db_session, test_tenant):
    await _seed_config(db_session, test_tenant.id, mode=PRICING_MODE_MANUAL_OVERRIDE)
    result = await TenantPricingService.get_effective_rate(db_session, test_tenant.id)
    assert result is None
