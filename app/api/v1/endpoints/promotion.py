from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user, require_admin
from app.schemas.auth import StandardSuccessResponse
from app.schemas.promotion import PromotionCreateRequest, PromotionUpdateRequest
from app.services.promotion_service import PromotionService

router = APIRouter()


# 1. Customer Endpoint
@router.get(
    "/customer/home-banner",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Home Banner (Customer)",
    description="Returns the highest-priority active promotion banner for the customer's tenant, or null if none exists.",
)
async def get_home_banner(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    banner = await PromotionService.get_home_banner(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Home banner retrieved successfully",
        data={"banner": banner.model_dump(mode="json") if banner else None},
    )


# 2. Admin Endpoints
@router.get(
    "/admin/promotions",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Promotions (Admin)",
    description="Returns all promotions for the admin's tenant, highest priority first.",
)
async def list_promotions(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    promotions = await PromotionService.list_promotions(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Promotions retrieved successfully",
        data={"promotions": [p.model_dump(mode="json") for p in promotions]},
    )


@router.post(
    "/admin/promotions",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Promotion (Admin)",
    description="Creates a new promotion banner for the admin's tenant.",
)
async def create_promotion(
    req: PromotionCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    promotion = await PromotionService.create_promotion(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Promotion created successfully",
        data={"promotion": promotion.model_dump(mode="json")},
    )


@router.put(
    "/admin/promotions/{promotion_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Promotion (Admin)",
    description="Updates an existing promotion banner. Only provided fields are changed.",
)
async def update_promotion(
    promotion_id: str,
    req: PromotionUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    promotion = await PromotionService.update_promotion(db, current_user, promotion_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Promotion updated successfully",
        data={"promotion": promotion.model_dump(mode="json")},
    )


@router.delete(
    "/admin/promotions/{promotion_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Promotion (Admin)",
    description="Permanently deletes a promotion banner.",
)
async def delete_promotion(
    promotion_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    await PromotionService.delete_promotion(db, current_user, promotion_id)
    return StandardSuccessResponse(
        success=True,
        message="Promotion deleted successfully",
        data=None,
    )
