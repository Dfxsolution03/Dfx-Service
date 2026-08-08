"""
Module 31 / Phase 1 — MarketRateSyncService orchestration tests. The
provider is mocked (via monkeypatching get_market_rate_provider) — these
tests exercise persistence/health/duplicate-detection logic only, never
real HTTP.
"""
from decimal import Decimal

from sqlalchemy import select, delete

from app.core.config import settings
from app.models.market_rate import MarketRate
from app.models.provider_health import ProviderHealth, STATUS_HEALTHY, STATUS_DEGRADED
from app.services import market_rate_sync_service as svc
from app.services.market_rate_sync_service import MarketRateSyncService
from app.services.market_rate_providers import MarketRateSnapshot, MarketRateProviderError


class _FakeProvider:
    def __init__(self, snapshot=None, error=None):
        self._snapshot = snapshot
        self._error = error

    async def fetch_rates(self):
        if self._error:
            raise self._error
        return self._snapshot


def _snapshot(gold=9800.0, silver=118.0):
    return MarketRateSnapshot(
        provider="METALPRICEAPI",
        gold_24k=gold,
        silver_999=silver,
        currency="INR",
        unit="PER_GRAM",
        raw_payload='{"success": true}',
        provider_metadata='{"note": "test"}',
    )


async def _cleanup(db_session, provider_name):
    await db_session.execute(delete(MarketRate).where(MarketRate.provider == provider_name))
    await db_session.execute(delete(ProviderHealth).where(ProviderHealth.provider == provider_name))
    await db_session.commit()


async def test_successful_sync_inserts_history_and_updates_health(db_session, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_RATE_PROVIDER", "METALPRICEAPI")
    monkeypatch.setattr(svc, "get_market_rate_provider", lambda: _FakeProvider(snapshot=_snapshot()))

    try:
        await MarketRateSyncService.sync(db_session)

        rows = (await db_session.execute(
            select(MarketRate).where(MarketRate.provider == "METALPRICEAPI")
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].gold_24k == Decimal("9800.0")
        assert rows[0].fetch_duration_ms is not None

        health = (await db_session.execute(
            select(ProviderHealth).where(ProviderHealth.provider == "METALPRICEAPI")
        )).scalar_one()
        assert health.status == STATUS_HEALTHY
        assert health.consecutive_failures == 0
        assert health.last_success_at is not None
        assert health.last_attempt_at is not None
    finally:
        await _cleanup(db_session, "METALPRICEAPI")


async def test_duplicate_value_skips_history_write(db_session, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_RATE_PROVIDER", "METALPRICEAPI")
    monkeypatch.setattr(svc, "get_market_rate_provider", lambda: _FakeProvider(snapshot=_snapshot(9800.0, 118.0)))

    try:
        await MarketRateSyncService.sync(db_session)  # first write
        await MarketRateSyncService.sync(db_session)  # identical — should skip

        rows = (await db_session.execute(
            select(MarketRate).where(MarketRate.provider == "METALPRICEAPI")
        )).scalars().all()
        assert len(rows) == 1  # not 2 — duplicate was not persisted

        # health still reflects the second successful attempt.
        health = (await db_session.execute(
            select(ProviderHealth).where(ProviderHealth.provider == "METALPRICEAPI")
        )).scalar_one()
        assert health.status == STATUS_HEALTHY
    finally:
        await _cleanup(db_session, "METALPRICEAPI")


async def test_changed_value_after_duplicate_writes_new_row(db_session, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_RATE_PROVIDER", "METALPRICEAPI")

    try:
        monkeypatch.setattr(svc, "get_market_rate_provider", lambda: _FakeProvider(snapshot=_snapshot(9800.0, 118.0)))
        await MarketRateSyncService.sync(db_session)

        monkeypatch.setattr(svc, "get_market_rate_provider", lambda: _FakeProvider(snapshot=_snapshot(9850.0, 118.0)))
        await MarketRateSyncService.sync(db_session)

        rows = (await db_session.execute(
            select(MarketRate).where(MarketRate.provider == "METALPRICEAPI")
        )).scalars().all()
        assert len(rows) == 2
    finally:
        await _cleanup(db_session, "METALPRICEAPI")


async def test_failed_sync_updates_health_without_writing_history(db_session, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_RATE_PROVIDER", "METALPRICEAPI")
    monkeypatch.setattr(
        svc, "get_market_rate_provider",
        lambda: _FakeProvider(error=MarketRateProviderError("simulated failure")),
    )

    try:
        await MarketRateSyncService.sync(db_session)

        rows = (await db_session.execute(
            select(MarketRate).where(MarketRate.provider == "METALPRICEAPI")
        )).scalars().all()
        assert len(rows) == 0  # no history row on failure

        health = (await db_session.execute(
            select(ProviderHealth).where(ProviderHealth.provider == "METALPRICEAPI")
        )).scalar_one()
        assert health.consecutive_failures == 1
        assert health.status == STATUS_DEGRADED
        assert health.last_error_message == "simulated failure"
        assert health.last_failure_at is not None
    finally:
        await _cleanup(db_session, "METALPRICEAPI")


async def test_failure_then_success_resets_consecutive_failures(db_session, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_RATE_PROVIDER", "METALPRICEAPI")

    try:
        monkeypatch.setattr(
            svc, "get_market_rate_provider",
            lambda: _FakeProvider(error=MarketRateProviderError("fail 1")),
        )
        await MarketRateSyncService.sync(db_session)

        monkeypatch.setattr(svc, "get_market_rate_provider", lambda: _FakeProvider(snapshot=_snapshot()))
        await MarketRateSyncService.sync(db_session)

        health = (await db_session.execute(
            select(ProviderHealth).where(ProviderHealth.provider == "METALPRICEAPI")
        )).scalar_one()
        assert health.consecutive_failures == 0
        assert health.status == STATUS_HEALTHY
        assert health.last_error_message is None
    finally:
        await _cleanup(db_session, "METALPRICEAPI")


async def test_existing_market_rate_history_never_overwritten(db_session, monkeypatch):
    """The very first row a prior test/run left behind (if any) must remain
    untouched — sync() only ever appends, confirmed by checking the earliest
    row's id is stable across two syncs with changing values."""
    monkeypatch.setattr(settings, "MARKET_RATE_PROVIDER", "METALPRICEAPI")
    try:
        monkeypatch.setattr(svc, "get_market_rate_provider", lambda: _FakeProvider(snapshot=_snapshot(9700.0, 117.0)))
        await MarketRateSyncService.sync(db_session)
        first_row = (await db_session.execute(
            select(MarketRate).where(MarketRate.provider == "METALPRICEAPI").order_by(MarketRate.fetched_at.asc())
        )).scalars().first()
        first_id, first_gold = first_row.id, first_row.gold_24k

        monkeypatch.setattr(svc, "get_market_rate_provider", lambda: _FakeProvider(snapshot=_snapshot(9999.0, 119.0)))
        await MarketRateSyncService.sync(db_session)

        reloaded_first = (await db_session.execute(
            select(MarketRate).where(MarketRate.id == first_id)
        )).scalar_one()
        assert reloaded_first.gold_24k == first_gold  # unchanged
    finally:
        await _cleanup(db_session, "METALPRICEAPI")
