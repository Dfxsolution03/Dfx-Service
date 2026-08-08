import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.promotion import Promotion
from app.repositories.promotion_repository import PromotionRepository

pytestmark = pytest.mark.asyncio


def _make(tenant_id, **kwargs):
    defaults = dict(
        id=f"promo_{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        title="Test Promotion",
        priority=0,
        is_active=True,
    )
    defaults.update(kwargs)
    return Promotion(**defaults)


async def test_create_and_get_by_id(db_session, test_tenant):
    promotion = _make(test_tenant.id)
    await PromotionRepository.create(db_session, promotion)
    await db_session.commit()

    fetched = await PromotionRepository.get_by_id_for_tenant(db_session, promotion.id, test_tenant.id)
    assert fetched is not None
    assert fetched.title == "Test Promotion"


async def test_get_by_id_wrong_tenant_returns_none(db_session, test_tenant):
    promotion = _make(test_tenant.id)
    await PromotionRepository.create(db_session, promotion)
    await db_session.commit()

    result = await PromotionRepository.get_by_id_for_tenant(db_session, promotion.id, "tnt_other")
    assert result is None


async def test_top_active_picks_highest_priority(db_session, test_tenant):
    low = _make(test_tenant.id, title="Low", priority=1)
    high = _make(test_tenant.id, title="High", priority=5)
    await PromotionRepository.create(db_session, low)
    await PromotionRepository.create(db_session, high)
    await db_session.commit()

    top = await PromotionRepository.get_top_active_for_tenant(db_session, test_tenant.id)
    assert top is not None
    assert top.title == "High"


async def test_top_active_excludes_inactive(db_session, test_tenant):
    promotion = _make(test_tenant.id, is_active=False)
    await PromotionRepository.create(db_session, promotion)
    await db_session.commit()

    top = await PromotionRepository.get_top_active_for_tenant(db_session, test_tenant.id)
    assert top is None


async def test_top_active_excludes_outside_date_window(db_session, test_tenant):
    expired = _make(
        test_tenant.id,
        title="Expired",
        end_date=datetime.now(timezone.utc) - timedelta(days=1),
    )
    await PromotionRepository.create(db_session, expired)
    await db_session.commit()

    top = await PromotionRepository.get_top_active_for_tenant(db_session, test_tenant.id)
    assert top is None


async def test_top_active_returns_none_when_no_promotions(db_session, test_tenant):
    top = await PromotionRepository.get_top_active_for_tenant(db_session, test_tenant.id)
    assert top is None


async def test_delete(db_session, test_tenant):
    promotion = _make(test_tenant.id)
    await PromotionRepository.create(db_session, promotion)
    await db_session.commit()

    await PromotionRepository.delete(db_session, promotion)
    await db_session.commit()

    result = await PromotionRepository.get_by_id_for_tenant(db_session, promotion.id, test_tenant.id)
    assert result is None
