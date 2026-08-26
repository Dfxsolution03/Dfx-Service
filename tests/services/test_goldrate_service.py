"""
JROS Service Tests — GoldRateService
======================================

Tests GoldRateService static methods directly against the real
Supabase PostgreSQL database (no HTTP layer).
"""

import uuid
from datetime import timedelta

import pytest
from app.core.config import settings
from app.models.auth import User
from app.models.goldrate import GoldRate
from app.schemas.goldrate import GoldRateCreateRequest, GoldRateUpdateRequest
from app.services.goldrate_service import GoldRateService, _today_ist
from app.exceptions.base import ConflictException, ResourceNotFoundException


class TestGetTodayRate:

    async def test_returns_none_when_not_set(self, db_session, admin_user: User):
        result = await GoldRateService.get_today_rate(db_session, admin_user)
        assert result is None


class TestCreateTodayRate:

    async def test_create_persists_rate(self, db_session, admin_user: User):
        req = GoldRateCreateRequest(rate_24k=9820.50)
        result = await GoldRateService.create_today_rate(db_session, admin_user, req)
        assert result.rate_24k == 9820.50
        assert result.created_by == admin_user.id
        assert result.tenant_id == admin_user.tenant_id

    async def test_create_duplicate_raises_conflict(self, db_session, admin_user: User):
        req = GoldRateCreateRequest(rate_24k=9000)
        await GoldRateService.create_today_rate(db_session, admin_user, req)

        with pytest.raises(ConflictException):
            await GoldRateService.create_today_rate(db_session, admin_user, GoldRateCreateRequest(rate_24k=9500))


class TestUpdateTodayRate:

    async def test_update_without_existing_raises_not_found(self, db_session, admin_user: User):
        req = GoldRateUpdateRequest(rate_24k=9500)
        with pytest.raises(ResourceNotFoundException):
            await GoldRateService.update_today_rate(db_session, admin_user, req)

    async def test_update_modifies_same_record(self, db_session, admin_user: User):
        created = await GoldRateService.create_today_rate(db_session, admin_user, GoldRateCreateRequest(rate_24k=9000))
        updated = await GoldRateService.update_today_rate(db_session, admin_user, GoldRateUpdateRequest(rate_24k=9600))

        assert updated.id == created.id
        assert updated.rate_24k == 9600

        fetched = await GoldRateService.get_today_rate(db_session, admin_user)
        assert fetched.id == created.id
        assert fetched.rate_24k == 9600


class TestGetCustomerTodayRate:

    async def test_returns_none_when_not_set(self, db_session, customer_user: User):
        result = await GoldRateService.get_customer_today_rate(db_session, customer_user)
        assert result is None

    async def test_reflects_admin_set_rate(self, db_session, admin_user: User, customer_user: User):
        # admin_user and customer_user share the same test_tenant fixture instance
        await GoldRateService.create_today_rate(db_session, admin_user, GoldRateCreateRequest(rate_24k=9750))

        result = await GoldRateService.get_customer_today_rate(db_session, customer_user)
        assert result is not None
        assert result.rate_24k == 9750


class TestCustomerRateFallback:
    """
    The tenant's daily rate is keyed to an exact calendar date, so at midnight
    IST a store that hasn't yet entered the new day's rate used to blank the
    customer's screen entirely. These cover the fallback that fixes that, and
    the two lines it must not cross: never serving a stale price as if it were
    today's, and never inventing one.
    """

    @staticmethod
    def _seed(tenant_id: str, days_ago: int, rate: float) -> GoldRate:
        d = _today_ist() - timedelta(days=days_ago)
        return GoldRate(
            id=f"gr_test_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            rate_24k=rate,
            effective_date=d,
            created_by="usr_test_seed",
        )

    async def test_todays_rate_is_preferred_over_older_ones(
        self, db_session, customer_user: User
    ):
        db_session.add(self._seed(customer_user.tenant_id, 2, 9000.0))
        db_session.add(self._seed(customer_user.tenant_id, 0, 9750.0))
        await db_session.commit()

        result = await GoldRateService.get_customer_today_rate(db_session, customer_user)
        assert result is not None
        assert result.rate_24k == 9750.0
        assert result.effective_date == _today_ist()

    async def test_yesterdays_rate_is_served_with_yesterdays_date(
        self, db_session, customer_user: User
    ):
        """The whole point: the price shows, but dated honestly so the client
        can label it rather than passing it off as today's."""
        yesterday = _today_ist() - timedelta(days=1)
        db_session.add(self._seed(customer_user.tenant_id, 1, 9123.0))
        await db_session.commit()

        result = await GoldRateService.get_customer_today_rate(db_session, customer_user)
        assert result is not None
        assert result.rate_24k == 9123.0
        assert result.effective_date == yesterday, "must NOT be restamped as today"

    async def test_rate_at_the_freshness_limit_is_still_served(
        self, db_session, customer_user: User
    ):
        limit = settings.CUSTOMER_RATE_FALLBACK_MAX_AGE_DAYS
        db_session.add(self._seed(customer_user.tenant_id, limit, 8888.0))
        await db_session.commit()

        result = await GoldRateService.get_customer_today_rate(db_session, customer_user)
        assert result is not None
        assert result.rate_24k == 8888.0

    async def test_rate_older_than_the_limit_is_unavailable(
        self, db_session, customer_user: User
    ):
        db_session.add(
            self._seed(
                customer_user.tenant_id,
                settings.CUSTOMER_RATE_FALLBACK_MAX_AGE_DAYS + 1,
                8000.0,
            )
        )
        await db_session.commit()

        result = await GoldRateService.get_customer_today_rate(db_session, customer_user)
        assert result is None, "a stale price must not be presented as current"

    async def test_no_rate_and_no_pricing_config_is_unavailable(
        self, db_session, customer_user: User
    ):
        result = await GoldRateService.get_customer_today_rate(db_session, customer_user)
        assert result is None

    async def test_never_returns_a_fabricated_rate(
        self, db_session, customer_user: User
    ):
        """Regression guard for the hardcoded 7450/88 placeholder that briefly
        existed here. A customer values their gold holdings off this number,
        so an invented one is worse than an empty screen — and that particular
        version also omitted the required updated_at, so it raised a
        ValidationError (HTTP 500) rather than returning anything at all."""
        result = await GoldRateService.get_customer_today_rate(db_session, customer_user)
        assert result is None
        if result is not None:  # pragma: no cover - defensive
            assert result.rate_24k != 7450.0
            assert result.silver_999 != 88.0

    async def test_another_tenants_rate_is_never_borrowed(
        self, db_session, customer_user: User
    ):
        """The fallback widened the lookup from one date to 'latest' — it must
        not also widen across tenants."""
        # Unique per run: gold_rates has a (tenant_id, effective_date) unique
        # constraint and this row belongs to no fixture that would clean it up.
        other_tenant = f"tnt_other_{uuid.uuid4().hex[:8]}"
        foreign_rate = self._seed(other_tenant, 1, 12345.0)
        db_session.add(foreign_rate)
        await db_session.commit()
        try:
            result = await GoldRateService.get_customer_today_rate(db_session, customer_user)
            assert result is None
        finally:
            await db_session.delete(foreign_rate)
            await db_session.commit()
