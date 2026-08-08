from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user
from app.schemas.auth import StandardSuccessResponse
from app.services.notification_service import NotificationService

router = APIRouter()


@router.get(
    "/customer/notifications",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Notifications (Customer)",
    description="Returns the authenticated customer's notifications, newest first.",
)
async def list_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    items = await NotificationService.get_my_notifications(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Notifications retrieved successfully",
        data={"notifications": [i.model_dump(mode="json") for i in items]},
    )


@router.get(
    "/customer/notifications/unread-count",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Unread Notification Count (Customer)",
    description="Returns the authenticated customer's unread notification count.",
)
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await NotificationService.get_unread_count(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Unread count retrieved successfully",
        data=result.model_dump(mode="json"),
    )


@router.put(
    "/customer/notifications/read-all",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark All Notifications as Read (Customer)",
    description="Marks all of the authenticated customer's unread notifications as read.",
)
async def mark_all_as_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await NotificationService.mark_all_as_read(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="All notifications marked as read",
        data={},
    )


@router.get(
    "/customer/notifications/{notification_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Notification Detail (Customer)",
    description="Returns a single notification. Own-only — 404 (not 403) if it isn't the caller's.",
)
async def get_notification_detail(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    item = await NotificationService.get_notification_detail(db, current_user, notification_id)
    return StandardSuccessResponse(
        success=True,
        message="Notification retrieved successfully",
        data={"notification": item.model_dump(mode="json")},
    )


@router.put(
    "/customer/notifications/{notification_id}/read",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark Notification as Read (Customer)",
    description="Marks a single notification as read. Own-only — 404 (not 403) if it isn't the caller's.",
)
async def mark_as_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    item = await NotificationService.mark_as_read(db, current_user, notification_id)
    return StandardSuccessResponse(
        success=True,
        message="Notification marked as read",
        data={"notification": item.model_dump(mode="json")},
    )
