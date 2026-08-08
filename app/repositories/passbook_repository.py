from typing import List
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.passbook import PassbookEntry
from app.models.enrollment import SchemeEnrollment


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
    async def get_recent_entries_for_customer(
        db: AsyncSession, tenant_id: str, customer_id: str, limit: int = 5
    ) -> List[PassbookEntry]:
        """
        Phase 6B — Customer Dashboard. Entries across ALL of a customer's
        enrollments, newest first. Joins through SchemeEnrollment (the only
        FK path from PassbookEntry to a customer) in a single query — avoids
        the N+1 that would result from looping get_entries_by_enrollment()
        once per active enrollment.
        """
        stmt = (
            select(PassbookEntry)
            .join(SchemeEnrollment, PassbookEntry.enrollment_id == SchemeEnrollment.id)
            .where(
                PassbookEntry.tenant_id == tenant_id,
                SchemeEnrollment.customer_id == customer_id,
            )
            .order_by(PassbookEntry.entry_date.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_gold_totals_for_customer(
        db: AsyncSession, tenant_id: str, customer_id: str
    ) -> dict:
        """
        Phase 6B — Customer Dashboard. Lifetime-accurate gold accumulation
        total, via SUM()/COUNT() rather than fetching every row — per
        explicit instruction, NOT derived from get_recent_entries_for_customer's
        bounded window. Same join path as above, no LIMIT.
        """
        stmt = (
            select(
                func.coalesce(func.sum(PassbookEntry.gold_weight), 0.0),
                func.coalesce(func.sum(PassbookEntry.amount), 0.0),
                func.count(PassbookEntry.id),
            )
            .join(SchemeEnrollment, PassbookEntry.enrollment_id == SchemeEnrollment.id)
            .where(
                PassbookEntry.tenant_id == tenant_id,
                SchemeEnrollment.customer_id == customer_id,
            )
        )
        result = await db.execute(stmt)
        total_gold_weight, total_amount_paid, entry_count = result.one()
        return {
            "total_gold_weight": float(total_gold_weight),
            "total_amount_paid": float(total_amount_paid),
            "entry_count": int(entry_count),
        }

    @staticmethod
    async def create_entry(db: AsyncSession, entry: PassbookEntry) -> PassbookEntry:
        """
        Infrastructure for the future Payments module — not called by any
        route in this module (entries are never created automatically here).
        """
        db.add(entry)
        return entry
