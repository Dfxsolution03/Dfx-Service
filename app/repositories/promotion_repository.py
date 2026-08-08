from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promotion import Promotion


class PromotionRepository:
    @staticmethod
    async def get_by_id_for_tenant(
        db: AsyncSession, promotion_id: str, tenant_id: str
    ) -> Optional[Promotion]:
        stmt = select(Promotion).where(
            Promotion.id == promotion_id, Promotion.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_tenant(db: AsyncSession, tenant_id: str) -> List[Promotion]:
        stmt = (
            select(Promotion)
            .where(Promotion.tenant_id == tenant_id)
            .order_by(Promotion.priority.desc(), Promotion.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_top_active_for_tenant(db: AsyncSession, tenant_id: str) -> Optional[Promotion]:
        """Highest-priority active banner within its date window, if any.
        A null start_date/end_date means "no lower/upper bound"."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(Promotion)
            .where(
                Promotion.tenant_id == tenant_id,
                Promotion.is_active == True,  # noqa: E712
                or_(Promotion.start_date == None, Promotion.start_date <= now),  # noqa: E711
                or_(Promotion.end_date == None, Promotion.end_date >= now),  # noqa: E711
            )
            .order_by(Promotion.priority.desc(), Promotion.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, promotion: Promotion) -> Promotion:
        db.add(promotion)
        return promotion

    @staticmethod
    async def delete(db: AsyncSession, promotion: Promotion) -> None:
        await db.delete(promotion)
