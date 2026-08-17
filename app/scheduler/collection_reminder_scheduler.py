"""Phase 7 — thin scheduler wiring for overdue reminders.

Same strict boundary as market_rate_scheduler: this only acquires a session and
calls the existing CollectionService.run_due_reminders() — no business logic
here. That engine is already repeated-run safe, concurrency safe (UNIQUE per
enrollment+due_date), and stops on payment (next_due_date advances). Delivery is
IN_APP only; nothing external is faked.

Constructed here, started by app.main's lifespan only when
settings.ENABLE_COLLECTION_REMINDERS is true (default false).
"""
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.services.collection_service import CollectionService

_scheduler: Optional[AsyncIOScheduler] = None
COLLECTION_REMINDER_JOB_ID = "collection_reminders"


async def _run_reminders() -> None:
    # tenant_id=None → scans every tenant; each row stays tenant-scoped.
    async with AsyncSessionFactory() as db:
        await CollectionService.run_due_reminders(db)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_reminders,
        "interval",
        hours=settings.COLLECTION_REMINDER_INTERVAL_HOURS,
        id=COLLECTION_REMINDER_JOB_ID,
        replace_existing=True,
        # coalesce + max_instances=1: a missed/slow run never stacks a second
        # concurrent invocation of the engine.
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(),
    )
    return scheduler


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = create_scheduler()
    return _scheduler
