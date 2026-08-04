"""
JROS Service Tests — GoldRateService
======================================

Tests GoldRateService static methods directly against the real
Supabase PostgreSQL database (no HTTP layer).
"""

import pytest
from app.models.auth import User
from app.schemas.goldrate import GoldRateCreateRequest, GoldRateUpdateRequest
from app.services.goldrate_service import GoldRateService
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
