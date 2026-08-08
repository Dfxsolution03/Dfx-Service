"""
Module 31 / Phase 1 — thin scheduler.

Strict boundary: this module only acquires a DB session and calls
MarketRateSyncService.sync(). No retry/validation/health-tracking/business
logic belongs here — all of that lives in the service layer.

Runs one sync immediately at registration (next_run_time=now) in addition
to the interval, so a fresh deployment doesn't wait a full interval before
its first MarketRate row exists.

The scheduler is constructed here but only started by app.main's lifespan
when settings.ENABLE_MARKET_RATE_SYNC is true (default false) — see
app/main.py.
"""

from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.services.market_rate_sync_service import MarketRateSyncService

_scheduler: Optional[AsyncIOScheduler] = None

MARKET_RATE_SYNC_JOB_ID = "market_rate_sync"


async def _run_sync() -> None:
    """The entire job body — acquire a session, call the one service
    method. Nothing else."""
    async with AsyncSessionFactory() as db:
        await MarketRateSyncService.sync(db)


def create_scheduler() -> AsyncIOScheduler:
    """Builds (but does not start) the scheduler and registers the market
    rate sync job on it."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_sync,
        "interval",
        minutes=settings.MARKET_RATE_SYNC_INTERVAL_MINUTES,
        id=MARKET_RATE_SYNC_JOB_ID,
        replace_existing=True,
        next_run_time=datetime.now(),  # immediate sync on startup, not just interval
    )
    return scheduler


def get_scheduler() -> AsyncIOScheduler:
    """Module-level singleton so app.main's startup/shutdown hooks operate
    on the same scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = create_scheduler()
    return _scheduler
