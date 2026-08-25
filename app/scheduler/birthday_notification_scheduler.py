"""Thin scheduler wiring for customer birthday wishes.

Same strict boundary as the collection/market schedulers: acquires a session and
calls BirthdayNotificationService.run_birthday_wishes() once a day — no business
logic here. That engine is repeated-run safe (one wish per customer per birthday)
and never fabricates a push delivery.

Constructed here, started by app.main's lifespan only when
settings.ENABLE_BIRTHDAY_NOTIFICATIONS is true (default false).
"""
from datetime import timezone, timedelta
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.services.birthday_notification_service import BirthdayNotificationService

_scheduler: Optional[AsyncIOScheduler] = None
_IST = timezone(timedelta(hours=5, minutes=30))
BIRTHDAY_NOTIFICATION_JOB_ID = "birthday_wishes"


async def _run_birthday_wishes() -> None:
    # tenant_id=None → scans every tenant; each notification stays tenant-scoped.
    async with AsyncSessionFactory() as db:
        await BirthdayNotificationService.run_birthday_wishes(db)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=_IST)
    scheduler.add_job(
        _run_birthday_wishes,
        "cron",
        hour=settings.BIRTHDAY_NOTIFICATION_HOUR_IST,
        minute=0,
        id=BIRTHDAY_NOTIFICATION_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return scheduler


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = create_scheduler()
    return _scheduler
