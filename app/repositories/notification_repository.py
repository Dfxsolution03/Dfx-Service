import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, DeviceToken


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


class DeviceTokenRepository:
    """Phase 7 — push device registrations. Every read/write is tenant-scoped."""

    @staticmethod
    async def get_by_token(db: AsyncSession, tenant_id: str, token: str) -> Optional[DeviceToken]:
        stmt = select(DeviceToken).where(
            DeviceToken.tenant_id == tenant_id, DeviceToken.token == token
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def upsert(
        db: AsyncSession, tenant_id: str, user_id: str, token: str, platform: str, provider: str
    ) -> DeviceToken:
        """Register or re-register a token. Idempotent per (tenant, token): an
        existing row is re-pointed at the current user/platform/provider and
        reactivated (a phone re-installing keeps one row, never duplicates)."""
        row = await DeviceTokenRepository.get_by_token(db, tenant_id, token)
        now = datetime.now(timezone.utc)
        if row:
            row.user_id = user_id
            row.platform = platform
            row.provider = provider
            row.is_active = True
            row.last_seen_at = now
            return row
        row = DeviceToken(
            id=f"dvt_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            user_id=user_id,
            token=token,
            platform=platform,
            provider=provider,
            is_active=True,
            last_seen_at=now,
        )
        db.add(row)
        return row

    @staticmethod
    async def list_active_for_user(
        db: AsyncSession, tenant_id: str, user_id: str
    ) -> List[DeviceToken]:
        stmt = select(DeviceToken).where(
            DeviceToken.tenant_id == tenant_id,
            DeviceToken.user_id == user_id,
            DeviceToken.is_active.is_(True),
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def deactivate(db: AsyncSession, tenant_id: str, user_id: str, token: str) -> bool:
        """Deactivate one of the caller's tokens (logout / token rotation).
        Returns True if a row was affected."""
        row = await DeviceTokenRepository.get_by_token(db, tenant_id, token)
        if not row or row.user_id != user_id:
            return False
        row.is_active = False
        return True
