from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_pricing import TenantPricingConfig


class TenantPricingRepository:
    """
    Module 31 / Phase 0 — plain data access only. Resolving a tenant's
    effective selling rate belongs to TenantPricingService, not here. Phase
    0 scaffolding — no caller exists yet.
    """

    @staticmethod
    async def get_by_tenant(db: AsyncSession, tenant_id: str) -> Optional[TenantPricingConfig]:
        stmt = select(TenantPricingConfig).where(TenantPricingConfig.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, config: TenantPricingConfig) -> TenantPricingConfig:
        db.add(config)
        return config
