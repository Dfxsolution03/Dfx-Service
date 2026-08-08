"""
Module 31 / Phase 1 — MarketRateSyncService.

Orchestrates one sync attempt: fetch from the configured provider, validate,
persist a MarketRate history row (skipping identical duplicates), and always
upsert ProviderHealth — success or failure. Never overwrites a historical
MarketRate row; a failed fetch simply leaves the last successful row as
"latest" (no special-case read-side logic needed — see MarketRateRepository
.get_latest()).

Nothing calls this in production yet: the scheduler job that invokes it is
only started when settings.ENABLE_MARKET_RATE_SYNC is true (still false by
default at the end of Phase 1), and no customer-facing endpoint reads from
MarketRate yet (TenantPricingService, which will, remains unimplemented
until Phase 2).
"""

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.market_rate import MarketRate
from app.models.provider_health import (
    ProviderHealth,
    STATUS_HEALTHY,
    STATUS_DEGRADED,
    STATUS_DOWN,
)
from app.repositories.market_rate_repository import MarketRateRepository
from app.repositories.provider_health_repository import ProviderHealthRepository
from app.services.market_rate_providers import get_market_rate_provider, MarketRateSnapshot


def _compute_status(consecutive_failures: int) -> str:
    if consecutive_failures == 0:
        return STATUS_HEALTHY
    if consecutive_failures <= 2:
        return STATUS_DEGRADED
    return STATUS_DOWN


def _as_decimal(value: Optional[float]) -> Optional[Decimal]:
    return Decimal(str(value)) if value is not None else None


class MarketRateSyncService:
    @staticmethod
    async def sync(db: AsyncSession) -> None:
        provider_name = settings.MARKET_RATE_PROVIDER.upper()
        provider_adapter = get_market_rate_provider()

        health = await ProviderHealthRepository.get_by_provider(db, provider_name)
        if health is None:
            # consecutive_failures/status are explicit here (not left to the
            # mapped_column server_default) — this object is read/mutated in
            # Python immediately below, before any flush, so the ORM-level
            # default hasn't been applied yet and the attribute would
            # otherwise still be None.
            health = ProviderHealth(
                id=f"phl_{uuid.uuid4().hex[:12]}",
                provider=provider_name,
                consecutive_failures=0,
            )
            await ProviderHealthRepository.create(db, health)

        now = datetime.now(timezone.utc)
        health.last_attempt_at = now

        start = time.monotonic()
        try:
            snapshot: MarketRateSnapshot = await provider_adapter.fetch_rates()
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            health.last_failure_at = now
            health.consecutive_failures += 1
            health.last_error_message = str(exc)[:2000]
            health.status = _compute_status(health.consecutive_failures)
            await db.commit()
            logger.error(
                f"[MarketRateSync] {provider_name} fetch failed after {duration_ms}ms "
                f"(consecutive_failures={health.consecutive_failures}): {exc}",
                exc_info=True,
            )
            return

        duration_ms = int((time.monotonic() - start) * 1000)

        # Duplicate-write guard — skip persisting a new history row if the
        # values are identical to the latest stored record. Health still
        # updates (this was a successful attempt), so monitoring correctly
        # reflects an alive provider even during a flat-rate stretch.
        latest = await MarketRateRepository.get_latest(db)
        if (
            latest is not None
            and latest.gold_24k == _as_decimal(snapshot.gold_24k)
            and latest.silver_999 == _as_decimal(snapshot.silver_999)
        ):
            health.last_success_at = now
            health.consecutive_failures = 0
            health.last_error_message = None
            health.status = STATUS_HEALTHY
            await db.commit()
            logger.info(
                f"[MarketRateSync] {provider_name} fetch succeeded in {duration_ms}ms "
                f"— value unchanged, skipping duplicate write."
            )
            return

        market_rate = MarketRate(
            id=f"mkr_{uuid.uuid4().hex[:12]}",
            provider=snapshot.provider,
            gold_24k=_as_decimal(snapshot.gold_24k),
            silver_999=_as_decimal(snapshot.silver_999),
            currency=snapshot.currency,
            unit=snapshot.unit,
            raw_payload=snapshot.raw_payload,
            provider_metadata=snapshot.provider_metadata,
            fetch_duration_ms=duration_ms,
            fetched_at=now,
        )
        await MarketRateRepository.create(db, market_rate)

        health.last_success_at = now
        health.consecutive_failures = 0
        health.last_error_message = None
        health.status = STATUS_HEALTHY

        await db.commit()
        logger.info(
            f"[MarketRateSync] {provider_name} fetch succeeded in {duration_ms}ms — "
            f"gold_24k={snapshot.gold_24k} silver_999={snapshot.silver_999}"
        )
