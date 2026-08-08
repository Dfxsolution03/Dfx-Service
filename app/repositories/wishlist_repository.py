from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wishlist import WishlistItem


class WishlistRepository:
    @staticmethod
    async def get_items_by_user(db: AsyncSession, user_id: str, tenant_id: str) -> List[WishlistItem]:
        stmt = (
            select(WishlistItem)
            .where(WishlistItem.user_id == user_id, WishlistItem.tenant_id == tenant_id)
            .order_by(WishlistItem.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_item_by_user_and_product(
        db: AsyncSession, user_id: str, product_id: str, tenant_id: str
    ) -> Optional[WishlistItem]:
        stmt = select(WishlistItem).where(
            WishlistItem.user_id == user_id,
            WishlistItem.product_id == product_id,
            WishlistItem.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_item(db: AsyncSession, item: WishlistItem) -> WishlistItem:
        db.add(item)
        return item

    @staticmethod
    async def delete_item(db: AsyncSession, item: WishlistItem) -> None:
        await db.delete(item)
