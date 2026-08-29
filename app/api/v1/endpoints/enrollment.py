from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_admin_or_staff_module, get_current_user
from app.schemas.auth import StandardSuccessResponse
from app.schemas.enrollment import (
    EnrollmentCreateRequest,
    EnrollmentCloseRequest,
    EnrollmentRemarksUpdate,
    SchemeRedeemRequest,
)
from app.services.enrollment_service import EnrollmentService, SchemeBalanceService

router = APIRouter()


# 1. Admin Enrollment Endpoints (read-only)
@router.get(
    "/enrollments",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Enrollments (Admin)",
    description="Returns scheme enrollments for the admin's tenant, newest first. "
    "Optional customer_id filters to one customer's enrollments. Read-only.",
)
async def list_enrollments(
    customer_id: Optional[str] = Query(None, description="Filter to a single customer's enrollments"),
    current_user: User = Depends(require_admin_or_staff_module("enrollments")),
    db: AsyncSession = Depends(get_async_db),
):
    enrollments = await EnrollmentService.get_enrollments(db, current_user, customer_id)
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


@router.patch(
    "/enrollments/{enrollment_id}/remarks",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Enrollment Remarks (Admin/Staff)",
    description="Edits the enrollment's free-text remark (metadata only). Financial history is untouched.",
)
async def update_enrollment_remarks(
    enrollment_id: str,
    req: EnrollmentRemarksUpdate,
    current_user: User = Depends(require_admin_or_staff_module("enrollments")),
    db: AsyncSession = Depends(get_async_db),
):
    enrollment = await EnrollmentService.update_remarks(db, current_user, enrollment_id, req.remarks)
    return StandardSuccessResponse(
        success=True,
        message="Enrollment remarks updated",
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


# 3. Scheme balance / closure / redemption (Admin)
@router.get(
    "/enrollments/{enrollment_id}/balance",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Scheme Balance And Redemption History (Admin)",
    description=(
        "Authoritative scheme-credit position of one enrollment: successful contributions, "
        "amount already redeemed, available balance, closure details, and the full redemption "
        "history with the sale each redemption settled. Every figure is derived from the "
        "contribution and redemption ledgers — nothing is cached, and no bonus is applied "
        "(the product has no numeric bonus rule)."
    ),
)
async def get_enrollment_balance(
    enrollment_id: str,
    current_user: User = Depends(require_admin_or_staff_module("enrollments")),
    db: AsyncSession = Depends(get_async_db),
):
    balance = await SchemeBalanceService.get_balance(db, current_user, enrollment_id)
    return StandardSuccessResponse(
        success=True,
        message="Scheme balance retrieved successfully",
        data={"balance": balance.model_dump(mode="json")},
    )


@router.post(
    "/enrollments/{enrollment_id}/close",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Close A Scheme Enrollment (Admin)",
    description=(
        "Stops future contributions and records who closed it, when, and why. Nothing is "
        "deleted and no contribution is rewritten: the balance already paid in is preserved and "
        "stays redeemable against a future jewellery purchase. Closing never refunds and never "
        "forfeits. Requires a reason."
    ),
)
async def close_enrollment(
    enrollment_id: str,
    req: EnrollmentCloseRequest,
    current_user: User = Depends(require_admin_or_staff_module("enrollments")),
    db: AsyncSession = Depends(get_async_db),
):
    balance = await SchemeBalanceService.close_enrollment(db, current_user, enrollment_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Scheme closed successfully",
        data={"balance": balance.model_dump(mode="json")},
    )


@router.post(
    "/enrollments/{enrollment_id}/redeem",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Redeem Scheme Balance Against An Invoice (Admin)",
    description=(
        "Applies the customer's accumulated scheme balance to an existing jewellery invoice in "
        "one transaction: writes an immutable redemption record and appends a "
        "source=SCHEME_REDEMPTION row to the invoice's existing payment ledger, so the invoice "
        "settles without the amount ever being counted as cash collected. Several partial "
        "redemptions against one enrollment are allowed; leftover balance stays available for a "
        "future purchase. Rejects an amount above the available balance or above the invoice's "
        "outstanding, and refuses a returned or cancelled sale. The enrollment becomes REDEEMED "
        "once its balance reaches zero."
    ),
)
async def redeem_scheme_balance(
    enrollment_id: str,
    req: SchemeRedeemRequest,
    current_user: User = Depends(require_admin_or_staff_module("enrollments")),
    db: AsyncSession = Depends(get_async_db),
):
    balance = await SchemeBalanceService.redeem_against_sale(db, current_user, enrollment_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Scheme balance redeemed successfully",
        data={"balance": balance.model_dump(mode="json")},
    )
