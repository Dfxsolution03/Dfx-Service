import uuid
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.notification import Notification
from app.repositories.notification_repository import NotificationRepository
from app.exceptions.base import ForbiddenException, ResourceNotFoundException
from app.schemas.notification import (
    NotificationResponse,
    NotificationUnreadCountResponse,
    NotificationType,
)


class NotificationService:
    @staticmethod
    async def get_my_notifications(db: AsyncSession, current_user: User) -> List[NotificationResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        items = await NotificationRepository.get_by_user(db, current_user.id, current_user.tenant_id)
        return [NotificationResponse.model_validate(i) for i in items]

    @staticmethod
    async def get_notification_detail(
        db: AsyncSession, current_user: User, notification_id: str
    ) -> NotificationResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        item = await NotificationRepository.get_by_id_for_user(
            db, notification_id, current_user.id, current_user.tenant_id
        )
        if not item:
            raise ResourceNotFoundException(f"Notification ID '{notification_id}' not found")
        return NotificationResponse.model_validate(item)

    @staticmethod
    async def get_unread_count(db: AsyncSession, current_user: User) -> NotificationUnreadCountResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        count = await NotificationRepository.get_unread_count(db, current_user.id, current_user.tenant_id)
        return NotificationUnreadCountResponse(unread_count=count)

    @staticmethod
    async def mark_as_read(
        db: AsyncSession, current_user: User, notification_id: str
    ) -> NotificationResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        item = await NotificationRepository.get_by_id_for_user(
            db, notification_id, current_user.id, current_user.tenant_id
        )
        if not item:
            raise ResourceNotFoundException(f"Notification ID '{notification_id}' not found")
        item.is_read = True
        await db.commit()
        await db.refresh(item)
        return NotificationResponse.model_validate(item)

    @staticmethod
    async def mark_all_as_read(db: AsyncSession, current_user: User) -> None:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        await NotificationRepository.mark_all_read(db, current_user.id, current_user.tenant_id)
        await db.commit()

    @staticmethod
    async def create_notification(
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        title: str,
        message: str,
        type: NotificationType,
    ) -> Notification:
        """Internal helper for other services (scheme/payment/support/KYC
        events) to raise a notification. Not exposed as a public endpoint —
        no Flutter or admin caller creates notifications directly yet."""
        notification = Notification(
            id=f"ntf_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
            message=message,
            type=type,
        )
        await NotificationRepository.create(db, notification)
        return notification
