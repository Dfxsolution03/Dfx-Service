"""
Module 31 — scaffolding/scheduler/configuration tests.

Phase 0 established these as scaffolding-only assertions (both services
raised NotImplementedError unconditionally). Phase 1 implements
MarketRateSyncService for real, so that expectation is updated here to
match — TenantPricingService remains untouched scaffolding (Phase 2).
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.services.tenant_pricing_service import TenantPricingService
from app.scheduler.market_rate_scheduler import create_scheduler, MARKET_RATE_SYNC_JOB_ID


# --- Configuration loading ---------------------------------------------

def test_market_rate_settings_have_sensible_defaults():
    assert settings.ENABLE_MARKET_RATE_SYNC is False
    assert settings.MARKET_RATE_PROVIDER == "METALPRICEAPI"
    assert settings.MARKET_RATE_SYNC_INTERVAL_MINUTES == 10
    assert settings.MARKET_RATE_FETCH_TIMEOUT_SECONDS == 10
    assert settings.MARKET_RATE_RETRY_COUNT == 3
    assert settings.MARKET_RATE_RETRY_DELAY_SECONDS == 2
    # API keys default empty — no user configuration required.
    assert settings.METALPRICEAPI_KEY == ""
    assert settings.IBJA_API_KEY == ""
    assert settings.GOLDAPI_KEY == ""


# --- Scheduler registration ---------------------------------------------

def test_create_scheduler_registers_sync_job():
    scheduler = create_scheduler()
    assert isinstance(scheduler, AsyncIOScheduler)
    job = scheduler.get_job(MARKET_RATE_SYNC_JOB_ID)
    assert job is not None
    assert job.trigger.interval.total_seconds() == settings.MARKET_RATE_SYNC_INTERVAL_MINUTES * 60


def test_scheduler_runs_immediately_on_registration():
    """Phase 1 requirement: don't wait a full interval for the first row."""
    before = datetime.now()
    scheduler = create_scheduler()
    job = scheduler.get_job(MARKET_RATE_SYNC_JOB_ID)
    assert job.next_run_time is not None
    # Immediate means "now", not "one interval from now".
    assert job.next_run_time.replace(tzinfo=None) <= before + timedelta(seconds=5)


async def test_scheduler_execution_calls_sync_service():
    """Scheduler execution test — the job body must call
    MarketRateSyncService.sync() exactly once per run and nothing else
    (thin-scheduler contract)."""
    from app.scheduler import market_rate_scheduler as sched_module

    with patch.object(sched_module.MarketRateSyncService, "sync", new=AsyncMock()) as mock_sync:
        await sched_module._run_sync()
        mock_sync.assert_called_once()


# --- Service scaffolding (Phase 2 not started) ---------------------------

async def test_tenant_pricing_service_not_implemented(db_session, test_tenant):
    with pytest.raises(NotImplementedError):
        await TenantPricingService.get_effective_rate(db_session, test_tenant.id)
