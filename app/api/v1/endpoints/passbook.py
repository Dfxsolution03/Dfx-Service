from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user, require_admin_only
from app.schemas.auth import StandardSuccessResponse
from app.services.passbook_service import PassbookService

router = APIRouter()


@router.get(
    "/passbooks/{enrollment_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Passbook (Admin)",
    description="Read-only view of a customer's passbook for any enrollment in the admin's tenant.",
)
async def get_passbook_admin(
    enrollment_id: str,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    passbook = await PassbookService.get_passbook_admin(db, current_user, enrollment_id)
    return StandardSuccessResponse(
        success=True,
        message="Passbook retrieved successfully",
        data={"passbook": passbook.model_dump(mode="json")},
    )


@router.get(
    "/customer/passbooks/{enrollment_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get My Passbook (Customer)",
    description="Read-only view of the authenticated customer's own passbook for one of their enrollments.",
)
async def get_passbook_customer(
    enrollment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    passbook = await PassbookService.get_passbook_customer(db, current_user, enrollment_id)
    return StandardSuccessResponse(
        success=True,
        message="Passbook retrieved successfully",
        data={"passbook": passbook.model_dump(mode="json")},
    )
