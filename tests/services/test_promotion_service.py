import pytest

from app.exceptions.base import ResourceNotFoundException
from app.schemas.promotion import PromotionCreateRequest, PromotionUpdateRequest
from app.services.promotion_service import PromotionService

pytestmark = pytest.mark.asyncio


async def test_get_home_banner_returns_none_when_no_promotion(db_session, customer_user):
    banner = await PromotionService.get_home_banner(db_session, customer_user)
    assert banner is None


async def test_create_then_get_home_banner(db_session, admin_user, customer_user):
    req = PromotionCreateRequest(title="No Making Charges", subtitle="On All Gold Jewellery", priority=1)
    created = await PromotionService.create_promotion(db_session, admin_user, req)
    assert created.title == "No Making Charges"

    banner = await PromotionService.get_home_banner(db_session, customer_user)
    assert banner is not None
    assert banner.title == "No Making Charges"
    assert banner.store_name is not None


async def test_update_promotion(db_session, admin_user):
    created = await PromotionService.create_promotion(
        db_session, admin_user, PromotionCreateRequest(title="Original")
    )
    updated = await PromotionService.update_promotion(
        db_session, admin_user, created.id, PromotionUpdateRequest(title="Updated")
    )
    assert updated.title == "Updated"


async def test_update_missing_promotion_raises(db_session, admin_user):
    with pytest.raises(ResourceNotFoundException):
        await PromotionService.update_promotion(
            db_session, admin_user, "promo_does_not_exist", PromotionUpdateRequest(title="X")
        )


async def test_delete_promotion(db_session, admin_user, customer_user):
    created = await PromotionService.create_promotion(
        db_session, admin_user, PromotionCreateRequest(title="ToDelete")
    )
    await PromotionService.delete_promotion(db_session, admin_user, created.id)

    banner = await PromotionService.get_home_banner(db_session, customer_user)
    assert banner is None


async def test_inactive_promotion_not_returned_as_banner(db_session, admin_user, customer_user):
    await PromotionService.create_promotion(
        db_session, admin_user, PromotionCreateRequest(title="Inactive", is_active=False)
    )
    banner = await PromotionService.get_home_banner(db_session, customer_user)
    assert banner is None
