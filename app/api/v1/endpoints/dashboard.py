from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user
from app.schemas.auth import StandardSuccessResponse
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get(
    "/customer/dashboard",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Customer Dashboard (Phase 6B)",
    description=(
        "Single-call aggregation of profile, gold rate, scheme/enrollment "
        "summary, recent passbook activity, recent payments, wishlist count, "
        "open support ticket count, and featured products for the "
        "authenticated customer's home dashboard."
    ),
)
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    dashboard = await DashboardService.get_dashboard(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Dashboard retrieved successfully",
        data=dashboard.model_dump(mode="json"),
    )
