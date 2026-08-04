"""
JROS Repository Tests — GoldRateRepository
=============================================
"""

import uuid
from datetime import date, timedelta
from app.models.goldrate import GoldRate
from app.repositories.goldrate_repository import GoldRateRepository


class TestGoldRateRepository:

    async def test_get_rate_for_date_returns_none_when_absent(self, db_session, admin_user):
        result = await GoldRateRepository.get_rate_for_date(db_session, admin_user.tenant_id, date.today())
        assert result is None

    async def test_create_and_get_rate_for_date(self, db_session, admin_user):
        today = date.today()
        rate = GoldRate(
            id=f"gr_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            rate_24k=9820.0,
            effective_date=today,
            created_by=admin_user.id,
        )
        await GoldRateRepository.create_rate(db_session, rate)
        await db_session.commit()

        fetched = await GoldRateRepository.get_rate_for_date(db_session, admin_user.tenant_id, today)
        assert fetched is not None
        assert fetched.rate_24k == 9820.0

    async def test_get_rate_for_date_is_date_specific(self, db_session, admin_user):
        """A rate for yesterday must not be returned when querying today."""
        yesterday = date.today() - timedelta(days=1)
        rate = GoldRate(
            id=f"gr_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            rate_24k=9000.0,
            effective_date=yesterday,
            created_by=admin_user.id,
        )
        await GoldRateRepository.create_rate(db_session, rate)
        await db_session.commit()

        fetched_today = await GoldRateRepository.get_rate_for_date(db_session, admin_user.tenant_id, date.today())
        assert fetched_today is None

        fetched_yesterday = await GoldRateRepository.get_rate_for_date(db_session, admin_user.tenant_id, yesterday)
        assert fetched_yesterday is not None
