from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import STAFF_MODULE_NOTIFICATIONS
from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_admin_or_staff_module
from app.schemas.auth import StandardSuccessResponse
from app.schemas.notification_campaign import (
    NotificationCampaignCreateRequest,
    NotificationCampaignUpdateRequest,
)
from app.services.notification_campaign_service import NotificationCampaignService

router = APIRouter()
require_notifications = require_admin_or_staff_module(STAFF_MODULE_NOTIFICATIONS)


@router.post(
    "/admin/notifications",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Notification Draft (Admin)",
)
async def create_notification(
    req: NotificationCampaignCreateRequest,
    current_user: User = Depends(require_notifications),
    db: AsyncSession = Depends(get_async_db),
):
    campaign = await NotificationCampaignService.create(db, current_user, req)
    return StandardSuccessResponse(
        success=True, message="Notification draft created", data={"notification": campaign.model_dump(mode="json")}
    )


@router.get(
    "/admin/notifications",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Notifications (Admin)",
)
async def list_notifications(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_notifications),
    db: AsyncSession = Depends(get_async_db),
):
    items, total = await NotificationCampaignService.list_campaigns(db, current_user, status_filter, page, page_size)
    return StandardSuccessResponse(
        success=True,
        message="Notifications retrieved successfully",
        data={"notifications": [i.model_dump(mode="json") for i in items]},
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get(
    "/admin/notifications/{notification_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Notification Detail (Admin)",
)
async def get_notification_detail(
    notification_id: str,
    current_user: User = Depends(require_notifications),
    db: AsyncSession = Depends(get_async_db),
):
    item = await NotificationCampaignService.get_detail(db, current_user, notification_id)
    return StandardSuccessResponse(
        success=True, message="Notification retrieved successfully", data={"notification": item.model_dump(mode="json")}
    )


@router.put(
    "/admin/notifications/{notification_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit Notification Draft (Admin)",
)
async def update_notification(
    notification_id: str,
    req: NotificationCampaignUpdateRequest,
    current_user: User = Depends(require_notifications),
    db: AsyncSession = Depends(get_async_db),
):
    item = await NotificationCampaignService.update(db, current_user, notification_id, req)
    return StandardSuccessResponse(
        success=True, message="Notification updated", data={"notification": item.model_dump(mode="json")}
    )


@router.post(
    "/admin/notifications/{notification_id}/send",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Send Notification (Admin)",
)
async def send_notification(
    notification_id: str,
    current_user: User = Depends(require_notifications),
    db: AsyncSession = Depends(get_async_db),
):
    item = await NotificationCampaignService.send(db, current_user, notification_id)
    message = "Notification sent successfully" if item.status == "SENT" else "Notification could not be sent"
    return StandardSuccessResponse(success=item.status == "SENT", message=message, data={"notification": item.model_dump(mode="json")})


@router.delete(
    "/admin/notifications/{notification_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel/Delete Notification Draft (Admin)",
)
async def cancel_notification(
    notification_id: str,
    current_user: User = Depends(require_notifications),
    db: AsyncSession = Depends(get_async_db),
):
    item = await NotificationCampaignService.cancel(db, current_user, notification_id)
    return StandardSuccessResponse(
        success=True, message="Notification cancelled", data={"notification": item.model_dump(mode="json")}
    )
