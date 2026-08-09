from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_superadmin
from app.schemas.auth import StandardSuccessResponse
from app.schemas.platform_settings import PlatformSettingsUpdateRequest
from app.services.platform_settings_service import PlatformSettingsService

router = APIRouter()


@router.get(
    "/superadmin/platform/settings",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Platform Settings (SuperAdmin)",
    description="Non-sensitive platform configuration only — never returns a secret value.",
)
async def get_platform_settings(
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    settings_data = await PlatformSettingsService.get(db)
    return StandardSuccessResponse(success=True, message="Platform settings retrieved successfully", data=settings_data.model_dump(mode="json"))


@router.put(
    "/superadmin/platform/settings",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Platform Settings (SuperAdmin)",
)
async def update_platform_settings(
    req: PlatformSettingsUpdateRequest,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    settings_data = await PlatformSettingsService.update(db, current_user, req)
    return StandardSuccessResponse(success=True, message="Platform settings updated successfully", data=settings_data.model_dump(mode="json"))


@router.get(
    "/superadmin/platform/settings/status",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Platform Configuration Status (SuperAdmin)",
    description="Lightweight status-only view (maintenance mode + provider configured flags) for dashboard widgets.",
)
async def get_platform_settings_status(
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    status_data = await PlatformSettingsService.get_status(db)
    return StandardSuccessResponse(success=True, message="Platform status retrieved successfully", data=status_data.model_dump(mode="json"))
