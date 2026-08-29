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
    async def get_rate_on_or_before(
        db: AsyncSession, tenant_id: str, on_date: date
    ) -> Optional[GoldRate]:
        """Most recent published rate with effective_date <= on_date.

        Used to value a scheme contribution when no rate was published on the
        exact payment date (weekend, backdated entry): the rate that was
        actually in force then, never a rate published afterwards."""
        stmt = (
            select(GoldRate)
            .where(
                GoldRate.tenant_id == tenant_id,
                GoldRate.effective_date <= on_date,
            )
            .order_by(GoldRate.effective_date.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_latest_rate(
        db: AsyncSession, tenant_id: str
    ) -> Optional[GoldRate]:
        stmt = (
            select(GoldRate)
            .where(GoldRate.tenant_id == tenant_id)
            .order_by(GoldRate.effective_date.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_rate(db: AsyncSession, rate: GoldRate) -> GoldRate:
        db.add(rate)
        return rate
