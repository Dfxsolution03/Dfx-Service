from typing import List, Optional, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ROLE_CUSTOMER
from app.models.auth import User, Role
from app.models.enrollment import SchemeEnrollment, STATUS_ACTIVE
from app.models.notification import NotificationCampaign, Notification


class NotificationCampaignRepository:
    @staticmethod
    async def create(db: AsyncSession, campaign: NotificationCampaign) -> NotificationCampaign:
        db.add(campaign)
        return campaign

    @staticmethod
    async def get_by_id_for_tenant(
        db: AsyncSession, campaign_id: str, tenant_id: str
    ) -> Optional[NotificationCampaign]:
        stmt = select(NotificationCampaign).where(
            NotificationCampaign.id == campaign_id, NotificationCampaign.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_for_tenant(
        db: AsyncSession, tenant_id: str, status: Optional[str], page: int, page_size: int
    ) -> Tuple[List[NotificationCampaign], int]:
        conditions = [NotificationCampaign.tenant_id == tenant_id]
        if status:
            conditions.append(NotificationCampaign.status == status)

        count_stmt = select(func.count(NotificationCampaign.id))
        list_stmt = select(NotificationCampaign).order_by(NotificationCampaign.created_at.desc())
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
            list_stmt = list_stmt.where(cond)

        total = int((await db.execute(count_stmt)).scalar_one())
        list_stmt = list_stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await db.execute(list_stmt)).scalars().all()
        return list(rows), total

    @staticmethod
    async def list_all_customers(db: AsyncSession, tenant_id: str) -> List[User]:
        stmt = (
            select(User)
            .join(Role, User.role_id == Role.id)
            .where(User.tenant_id == tenant_id, Role.name == ROLE_CUSTOMER, User.is_active.is_(True))
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_customers_by_ids(db: AsyncSession, tenant_id: str, customer_ids: List[str]) -> List[User]:
        stmt = (
            select(User)
            .join(Role, User.role_id == Role.id)
            .where(
                User.tenant_id == tenant_id,
                Role.name == ROLE_CUSTOMER,
                User.is_active.is_(True),
                User.id.in_(customer_ids),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_customers_by_scheme(db: AsyncSession, tenant_id: str, scheme_id: str) -> List[User]:
        stmt = (
            select(User)
            .join(SchemeEnrollment, SchemeEnrollment.customer_id == User.id)
            .where(
                SchemeEnrollment.tenant_id == tenant_id,
                SchemeEnrollment.scheme_id == scheme_id,
                SchemeEnrollment.status == STATUS_ACTIVE,
                User.is_active.is_(True),
            )
        )
        result = await db.execute(stmt)
        return list(result.unique().scalars().all())

    @staticmethod
    async def bulk_create_notifications(db: AsyncSession, notifications: List[Notification]) -> None:
        db.add_all(notifications)
