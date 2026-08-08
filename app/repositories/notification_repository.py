from typing import List, Optional
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


class NotificationRepository:
    @staticmethod
    async def get_by_user(db: AsyncSession, user_id: str, tenant_id: str) -> List[Notification]:
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id, Notification.tenant_id == tenant_id)
            .order_by(Notification.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id_for_user(
        db: AsyncSession, notification_id: str, user_id: str, tenant_id: str
    ) -> Optional[Notification]:
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
            Notification.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_unread_count(db: AsyncSession, user_id: str, tenant_id: str) -> int:
        stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.tenant_id == tenant_id,
            Notification.is_read.is_(False),
        )
        result = await db.execute(stmt)
        return result.scalar_one()

    @staticmethod
    async def create(db: AsyncSession, notification: Notification) -> Notification:
        db.add(notification)
        return notification

    @staticmethod
    async def mark_all_read(db: AsyncSession, user_id: str, tenant_id: str) -> None:
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.tenant_id == tenant_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await db.execute(stmt)
