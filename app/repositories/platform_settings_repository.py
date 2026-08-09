from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_settings import PlatformSettings, PLATFORM_SETTINGS_SINGLETON_ID


class PlatformSettingsRepository:
    @staticmethod
    async def get(db: AsyncSession) -> Optional[PlatformSettings]:
        stmt = select(PlatformSettings).where(PlatformSettings.id == PLATFORM_SETTINGS_SINGLETON_ID)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_default(db: AsyncSession) -> PlatformSettings:
        row = PlatformSettings(id=PLATFORM_SETTINGS_SINGLETON_ID)
        db.add(row)
        return row
