from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_admin_or_staff_module, get_current_user
from app.schemas.auth import StandardSuccessResponse
from app.schemas.scheme import (
    SchemeCreateRequest,
    SchemeUpdateRequest,
    SchemeRequestCreate,
    SchemeRequestReject,
)
from app.services.scheme_service import SchemeService
from app.services.scheme_request_service import SchemeRequestService

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
    current_user: User = Depends(require_admin_or_staff_module("schemes")),
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
    current_user: User = Depends(require_admin_or_staff_module("schemes")),
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
    current_user: User = Depends(require_admin_or_staff_module("schemes")),
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
    current_user: User = Depends(require_admin_or_staff_module("schemes")),
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
    current_user: User = Depends(require_admin_or_staff_module("schemes")),
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


# ─── 3. Scheme Request lifecycle (Phase 2) ───

@router.post(
    "/scheme-requests",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Scheme Request (Customer)",
    description="Customer files a request to join a scheme. Creates a REQUESTED row only; "
                "no enrollment is created until an Admin approves and KYC is verified.",
)
async def create_scheme_request(
    req: SchemeRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await SchemeRequestService.create_request(db, current_user, req.scheme_id)
    return StandardSuccessResponse(
        success=True,
        message="Scheme request submitted successfully",
        data={"request": result.model_dump(mode="json")},
    )


@router.get(
    "/customer/scheme-requests",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List My Scheme Requests (Customer)",
    description="Returns the calling customer's own request history (REQUESTED/APPROVED/REJECTED).",
)
async def list_my_scheme_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    results = await SchemeRequestService.list_my_requests(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Scheme requests retrieved successfully",
        data={"requests": [r.model_dump(mode="json") for r in results]},
    )


@router.get(
    "/scheme-requests",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Scheme Requests (Admin/Staff)",
    description="Tenant-scoped request queue. Optional status filter (REQUESTED/APPROVED/REJECTED).",
)
async def list_scheme_requests(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(require_admin_or_staff_module("schemes", "enrollments")),
    db: AsyncSession = Depends(get_async_db),
):
    results = await SchemeRequestService.list_requests(db, current_user, status_filter)
    return StandardSuccessResponse(
        success=True,
        message="Scheme requests retrieved successfully",
        data={"requests": [r.model_dump(mode="json") for r in results]},
    )


@router.post(
    "/scheme-requests/{request_id}/approve",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve Scheme Request (Admin/Staff)",
    description="Approves a REQUESTED request and atomically creates its enrollment. "
                "Fails if the customer's live KYC status is not Verified.",
)
async def approve_scheme_request(
    request_id: str,
    current_user: User = Depends(require_admin_or_staff_module("schemes", "enrollments")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await SchemeRequestService.approve_request(db, current_user, request_id)
    return StandardSuccessResponse(
        success=True,
        message="Scheme request approved and enrollment created",
        data={"request": result.model_dump(mode="json")},
    )


@router.post(
    "/scheme-requests/{request_id}/reject",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject Scheme Request (Admin/Staff)",
    description="Rejects a REQUESTED request with a mandatory reason. The row remains in history.",
)
async def reject_scheme_request(
    request_id: str,
    req: SchemeRequestReject,
    current_user: User = Depends(require_admin_or_staff_module("schemes", "enrollments")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await SchemeRequestService.reject_request(db, current_user, request_id, req.reason)
    return StandardSuccessResponse(
        success=True,
        message="Scheme request rejected",
        data={"request": result.model_dump(mode="json")},
    )
