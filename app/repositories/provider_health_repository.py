from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider_health import ProviderHealth


class ProviderHealthRepository:
    """
    Module 31 / Phase 0 — plain data access only. Updating health after a
    sync attempt belongs to MarketRateSyncService, not here. Phase 0
    scaffolding — no caller exists yet.
    """

    @staticmethod
    async def get_by_provider(db: AsyncSession, provider: str) -> Optional[ProviderHealth]:
        stmt = select(ProviderHealth).where(ProviderHealth.provider == provider)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_all(db: AsyncSession) -> List[ProviderHealth]:
        stmt = select(ProviderHealth).order_by(ProviderHealth.provider)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create(db: AsyncSession, health: ProviderHealth) -> ProviderHealth:
        db.add(health)
        return health
