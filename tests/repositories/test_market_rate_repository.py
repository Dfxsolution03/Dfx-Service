"""
Module 31 / Phase 0 — model creation + repository scaffolding tests.
Creating a MarketRate row and reading it back exercises both the model
definition and MarketRateRepository in one pass.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.models.market_rate import MarketRate
from app.repositories.market_rate_repository import MarketRateRepository


async def test_create_and_get_latest(db_session):
    rate = MarketRate(
        id=f"mkr_test_{uuid.uuid4().hex[:12]}",
        provider="METALPRICEAPI",
        gold_24k=Decimal("9820.5000"),
        silver_999=Decimal("118.2500"),
        fetched_at=datetime.now(timezone.utc),
    )
    await MarketRateRepository.create(db_session, rate)
    await db_session.commit()

    try:
        latest = await MarketRateRepository.get_latest(db_session)
        assert latest is not None
        assert latest.id == rate.id
        assert latest.provider == "METALPRICEAPI"
        assert latest.gold_24k == Decimal("9820.5000")
        assert latest.currency == "INR"
        assert latest.unit == "PER_GRAM"
        assert latest.is_override is False
    finally:
        from sqlalchemy import delete
        await db_session.execute(delete(MarketRate).where(MarketRate.id == rate.id))
        await db_session.commit()


async def test_list_recent_returns_newest_first(db_session):
    ids = []
    try:
        for i in range(3):
            rate = MarketRate(
                id=f"mkr_test_{uuid.uuid4().hex[:12]}",
                provider="METALPRICEAPI",
                gold_24k=Decimal("9800.0000") + i,
                fetched_at=datetime.now(timezone.utc),
            )
            ids.append(rate.id)
            await MarketRateRepository.create(db_session, rate)
        await db_session.commit()

        recent = await MarketRateRepository.list_recent(db_session, limit=3)
        assert len(recent) >= 3
    finally:
        from sqlalchemy import delete
        await db_session.execute(delete(MarketRate).where(MarketRate.id.in_(ids)))
        await db_session.commit()
