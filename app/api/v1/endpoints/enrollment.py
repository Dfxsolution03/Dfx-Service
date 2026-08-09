from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_admin_or_staff_module, get_current_user
from app.schemas.auth import StandardSuccessResponse
from app.schemas.enrollment import EnrollmentCreateRequest
from app.services.enrollment_service import EnrollmentService

router = APIRouter()


# 1. Admin Enrollment Endpoints (read-only)
@router.get(
    "/enrollments",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Enrollments (Admin)",
    description="Returns all scheme enrollments for the admin's tenant. Read-only.",
)
async def list_enrollments(
    current_user: User = Depends(require_admin_or_staff_module("enrollments")),
    db: AsyncSession = Depends(get_async_db),
):
    enrollments = await EnrollmentService.get_enrollments(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Enrollments retrieved successfully",
        data={"enrollments": [e.model_dump(mode="json") for e in enrollments]},
    )


@router.get(
    "/enrollments/{enrollment_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Enrollment (Admin)",
    description="Returns a single enrollment by ID, scoped to the admin's tenant. Read-only.",
)
async def get_enrollment(
    enrollment_id: str,
    current_user: User = Depends(require_admin_or_staff_module("enrollments")),
    db: AsyncSession = Depends(get_async_db),
):
    enrollment = await EnrollmentService.get_enrollment_by_id(db, current_user, enrollment_id)
    return StandardSuccessResponse(
        success=True,
        message="Enrollment retrieved successfully",
        data={"enrollment": enrollment.model_dump(mode="json")},
    )


# 2. Customer Enrollment Endpoints
@router.post(
    "/customer/enrollments",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll in a Scheme (Customer)",
    description="Enrolls the customer into an active scheme belonging to their own tenant.",
)
async def create_enrollment(
    req: EnrollmentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    enrollment = await EnrollmentService.create_enrollment(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Enrolled in scheme successfully",
        data={"enrollment": enrollment.model_dump(mode="json")},
    )


@router.get(
    "/customer/enrollments",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List My Enrollments (Customer)",
    description="Returns the authenticated customer's own scheme enrollments.",
)
async def list_customer_enrollments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    enrollments = await EnrollmentService.get_customer_enrollments(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Enrollments retrieved successfully",
        data={"enrollments": [e.model_dump(mode="json") for e in enrollments]},
    )


@router.get(
    "/customer/enrollments/{enrollment_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get My Enrollment (Customer)",
    description="Returns a single enrollment belonging to the authenticated customer.",
)
async def get_customer_enrollment(
    enrollment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    enrollment = await EnrollmentService.get_customer_enrollment_by_id(db, current_user, enrollment_id)
    return StandardSuccessResponse(
        success=True,
        message="Enrollment retrieved successfully",
        data={"enrollment": enrollment.model_dump(mode="json")},
    )
