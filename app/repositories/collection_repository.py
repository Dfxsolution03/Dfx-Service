from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import SchemeEnrollment, STATUS_ACTIVE
from app.models.collection import CollectionReminder


class CollectionRepository:
    @staticmethod
    async def list_overdue_active(
        db: AsyncSession, today: date, window_days: Optional[int] = None,
        tenant_id: Optional[str] = None,
    ) -> List[SchemeEnrollment]:
        """ACTIVE enrollments whose next_due_date is overdue by >= 1 day.

        Phase 9: window_days is now an OPTIONAL lower bound. When None (the
        weekly-recurrence default) there is no lower bound — an installment keeps
        being picked up for as long as it stays overdue, so the every-7-day
        reminder never stops until a payment advances next_due_date. A positive
        window_days still applies the old inclusive lower bound (kept for
        backward compatibility). CLOSED/REDEEMED/COMPLETED/CANCELLED and
        not-yet-due enrollments are always excluded."""
        latest_due = today - timedelta(days=1)             # overdue by >=1 day
        stmt = select(SchemeEnrollment).where(
            SchemeEnrollment.status == STATUS_ACTIVE,
            SchemeEnrollment.next_due_date.is_not(None),
            SchemeEnrollment.next_due_date <= latest_due,
        )
        if window_days is not None:
            stmt = stmt.where(SchemeEnrollment.next_due_date >= today - timedelta(days=window_days))
        if tenant_id is not None:
            stmt = stmt.where(SchemeEnrollment.tenant_id == tenant_id)
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def create(db: AsyncSession, reminder: CollectionReminder) -> CollectionReminder:
        db.add(reminder)
        return reminder
