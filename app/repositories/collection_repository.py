from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import SchemeEnrollment, STATUS_ACTIVE
from app.models.collection import CollectionReminder


class CollectionRepository:
    @staticmethod
    async def list_overdue_active(
        db: AsyncSession, today: date, window_days: int, tenant_id: Optional[str] = None
    ) -> List[SchemeEnrollment]:
        """ACTIVE enrollments whose next_due_date is 1..window_days days past.
        CLOSED/REDEEMED/COMPLETED/CANCELLED are excluded (status == ACTIVE only);
        not-yet-due (next_due_date >= today) and beyond the window are excluded."""
        oldest_due = today - timedelta(days=window_days)   # inclusive lower bound
        latest_due = today - timedelta(days=1)             # overdue by >=1 day
        stmt = select(SchemeEnrollment).where(
            SchemeEnrollment.status == STATUS_ACTIVE,
            SchemeEnrollment.next_due_date.is_not(None),
            SchemeEnrollment.next_due_date >= oldest_due,
            SchemeEnrollment.next_due_date <= latest_due,
        )
        if tenant_id is not None:
            stmt = stmt.where(SchemeEnrollment.tenant_id == tenant_id)
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def create(db: AsyncSession, reminder: CollectionReminder) -> CollectionReminder:
        db.add(reminder)
        return reminder
