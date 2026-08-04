from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user, require_admin_only
from app.schemas.auth import StandardSuccessResponse
from app.schemas.scheme import SchemeCreateRequest, SchemeUpdateRequest
from app.services.scheme_service import SchemeService

router = APIRouter()


# 1. Admin Scheme Endpoints
@router.get(
    "/schemes",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Schemes (Admin)",
    description="Returns all schemes (active and inactive) for the admin's tenant.",
)
async def list_schemes(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    schemes = await SchemeService.get_schemes(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Schemes retrieved successfully",
        data={"schemes": [s.model_dump(mode="json") for s in schemes]},
    )


@router.get(
    "/schemes/{scheme_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Scheme (Admin)",
    description="Returns a single scheme by ID, scoped to the admin's tenant.",
)
async def get_scheme(
    scheme_id: str,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    scheme = await SchemeService.get_scheme_by_id(db, current_user, scheme_id)
    return StandardSuccessResponse(
        success=True,
        message="Scheme retrieved successfully",
        data={"scheme": scheme.model_dump(mode="json")},
    )


@router.post(
    "/schemes",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Scheme (Admin)",
    description="Creates a new gold savings scheme template for the admin's tenant.",
)
async def create_scheme(
    req: SchemeCreateRequest,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    scheme = await SchemeService.create_scheme(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Scheme created successfully",
        data={"scheme": scheme.model_dump(mode="json")},
    )


@router.put(
    "/schemes/{scheme_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Scheme (Admin)",
    description="Updates an existing scheme's fields, including reactivating it via is_active.",
)
async def update_scheme(
    scheme_id: str,
    req: SchemeUpdateRequest,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    scheme = await SchemeService.update_scheme(db, current_user, scheme_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Scheme updated successfully",
        data={"scheme": scheme.model_dump(mode="json")},
    )


@router.delete(
    "/schemes/{scheme_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate Scheme (Admin)",
    description="Soft-deletes a scheme by setting is_active=False. The record is never removed.",
)
async def deactivate_scheme(
    scheme_id: str,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    await SchemeService.deactivate_scheme(db, current_user, scheme_id)
    return StandardSuccessResponse(
        success=True,
        message="Scheme deactivated successfully",
        data={},
    )


# 2. Customer Scheme Endpoint
@router.get(
    "/customer/schemes",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Schemes (Customer)",
    description="Returns active-only schemes for the customer's tenant.",
)
async def list_customer_schemes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    schemes = await SchemeService.get_customer_schemes(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Schemes retrieved successfully",
        data={"schemes": [s.model_dump(mode="json") for s in schemes]},
    )
