from datetime import date
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goldrate import GoldRate


class GoldRateRepository:
    @staticmethod
    async def get_rate_for_date(
        db: AsyncSession, tenant_id: str, effective_date: date
    ) -> Optional[GoldRate]:
        stmt = select(GoldRate).where(
            GoldRate.tenant_id == tenant_id,
            GoldRate.effective_date == effective_date,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_rate(db: AsyncSession, rate: GoldRate) -> GoldRate:
        db.add(rate)
        return rate
