from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.passbook import PassbookEntry


class PassbookRepository:
    @staticmethod
    async def get_entries_by_enrollment(
        db: AsyncSession, enrollment_id: str, tenant_id: str
    ) -> List[PassbookEntry]:
        stmt = (
            select(PassbookEntry)
            .where(
                PassbookEntry.enrollment_id == enrollment_id,
                PassbookEntry.tenant_id == tenant_id,
            )
            .order_by(PassbookEntry.entry_number.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_entry(db: AsyncSession, entry: PassbookEntry) -> PassbookEntry:
        """
        Infrastructure for the future Payments module — not called by any
        route in this module (entries are never created automatically here).
        """
        db.add(entry)
        return entry
