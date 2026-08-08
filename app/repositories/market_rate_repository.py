from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_rate import MarketRate


class MarketRateRepository:
    """
    Module 31 / Phase 0 — plain data access only, no business logic (rate
    resolution/markup belongs to TenantPricingService; fetching from a
    provider belongs to MarketRateSyncService). Phase 0 scaffolding — no
    caller exists yet.
    """

    @staticmethod
    async def get_latest(db: AsyncSession) -> Optional[MarketRate]:
        stmt = select(MarketRate).order_by(MarketRate.fetched_at.desc()).limit(1)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_recent(db: AsyncSession, limit: int = 50) -> List[MarketRate]:
        stmt = select(MarketRate).order_by(MarketRate.fetched_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create(db: AsyncSession, market_rate: MarketRate) -> MarketRate:
        db.add(market_rate)
        return market_rate
