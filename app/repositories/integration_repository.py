import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import PlatformIntegration, Webhook


class IntegrationRepository:
    @staticmethod
    async def get_by_provider(db: AsyncSession, provider: str) -> Optional[PlatformIntegration]:
        stmt = select(PlatformIntegration).where(PlatformIntegration.provider == provider)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create(db: AsyncSession, provider: str) -> PlatformIntegration:
        row = await IntegrationRepository.get_by_provider(db, provider)
        if row:
            return row
        row = PlatformIntegration(id=f"itg_{uuid.uuid4().hex[:12]}", provider=provider, enabled=False)
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def list_all(db: AsyncSession) -> List[PlatformIntegration]:
        result = await db.execute(select(PlatformIntegration))
        return list(result.scalars().all())

    @staticmethod
    async def create_webhook(db: AsyncSession, webhook: Webhook) -> Webhook:
        db.add(webhook)
        return webhook

    @staticmethod
    async def list_webhooks(db: AsyncSession) -> List[Webhook]:
        result = await db.execute(select(Webhook).order_by(Webhook.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def get_webhook_by_id(db: AsyncSession, webhook_id: str) -> Optional[Webhook]:
        stmt = select(Webhook).where(Webhook.id == webhook_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def delete_webhook(db: AsyncSession, webhook: Webhook) -> None:
        await db.delete(webhook)
