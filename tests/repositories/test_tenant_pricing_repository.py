"""Module 31 / Phase 0 — model creation + repository scaffolding tests."""
import uuid

from app.models.tenant_pricing import TenantPricingConfig, PRICING_MODE_LIVE_MARKET
from app.repositories.tenant_pricing_repository import TenantPricingRepository


async def test_create_and_get_by_tenant(db_session, test_tenant):
    config = TenantPricingConfig(
        id=f"tpc_test_{uuid.uuid4().hex[:12]}",
        tenant_id=test_tenant.id,
    )
    await TenantPricingRepository.create(db_session, config)
    await db_session.commit()

    try:
        fetched = await TenantPricingRepository.get_by_tenant(db_session, test_tenant.id)
        assert fetched is not None
        assert fetched.tenant_id == test_tenant.id
        assert fetched.mode == PRICING_MODE_LIVE_MARKET  # default
    finally:
        from sqlalchemy import delete
        await db_session.execute(delete(TenantPricingConfig).where(TenantPricingConfig.id == config.id))
        await db_session.commit()


async def test_get_by_tenant_returns_none_when_absent(db_session):
    result = await TenantPricingRepository.get_by_tenant(db_session, "tnt_does_not_exist")
    assert result is None
