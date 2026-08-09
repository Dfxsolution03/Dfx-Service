from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_admin_or_staff_module, get_current_user
from app.schemas.auth import StandardSuccessResponse
from app.schemas.goldrate import GoldRateCreateRequest, GoldRateUpdateRequest
from app.services.goldrate_service import GoldRateService

router = APIRouter()


# 1. Admin Gold Rate Endpoints
@router.get(
    "/gold-rates/today",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Today's Gold Rate (Admin)",
    description="Returns today's 24K gold rate for the admin's tenant, or null if not yet set.",
)
async def get_today_rate(
    current_user: User = Depends(require_admin_or_staff_module("gold_rate")),
    db: AsyncSession = Depends(get_async_db),
):
    rate = await GoldRateService.get_today_rate(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Today's gold rate retrieved successfully",
        data={"rate": rate.model_dump(mode="json") if rate else None},
    )


@router.post(
    "/gold-rates/today",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Today's Gold Rate (Admin)",
    description="Creates today's 24K gold rate for the admin's tenant. Fails if already set.",
)
async def create_today_rate(
    req: GoldRateCreateRequest,
    current_user: User = Depends(require_admin_or_staff_module("gold_rate")),
    db: AsyncSession = Depends(get_async_db),
):
    rate = await GoldRateService.create_today_rate(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Today's gold rate created successfully",
        data={"rate": rate.model_dump(mode="json")},
    )


@router.put(
    "/gold-rates/today",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Today's Gold Rate (Admin)",
    description="Updates today's 24K gold rate for the admin's tenant. Fails if not yet set.",
)
async def update_today_rate(
    req: GoldRateUpdateRequest,
    current_user: User = Depends(require_admin_or_staff_module("gold_rate")),
    db: AsyncSession = Depends(get_async_db),
):
    rate = await GoldRateService.update_today_rate(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Today's gold rate updated successfully",
        data={"rate": rate.model_dump(mode="json")},
    )


# 2. Customer Gold Rate Endpoint
@router.get(
    "/customer/gold-rate",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Today's Gold Rate (Customer)",
    description="Returns today's 24K gold rate for the customer's tenant, or null if not yet set.",
)
async def get_customer_today_rate(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    rate = await GoldRateService.get_customer_today_rate(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Today's gold rate retrieved successfully",
        data={"rate": rate.model_dump(mode="json") if rate else None},
    )
