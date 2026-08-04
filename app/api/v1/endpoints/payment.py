from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user, require_admin_only
from app.schemas.auth import StandardSuccessResponse
from app.schemas.payment import PaymentManualCreateRequest, PaymentUpdateRequest
from app.services.payment_service import PaymentService

router = APIRouter()


# 1. Admin Payment Endpoints
@router.get(
    "/payments",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Payments (Admin)",
    description="Returns all payments for the admin's tenant.",
)
async def list_payments(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    payments = await PaymentService.get_payments(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Payments retrieved successfully",
        data={"payments": [p.model_dump(mode="json") for p in payments]},
    )


@router.get(
    "/payments/{payment_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Payment (Admin)",
    description="Returns a single payment by ID, scoped to the admin's tenant.",
)
async def get_payment(
    payment_id: str,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    payment = await PaymentService.get_payment_by_id(db, current_user, payment_id)
    return StandardSuccessResponse(
        success=True,
        message="Payment retrieved successfully",
        data={"payment": payment.model_dump(mode="json")},
    )


@router.post(
    "/payments/manual",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record Manual Payment (Admin)",
    description="Records a payment collected outside the app (cash, bank transfer, cheque, etc.). No gateway involved.",
)
async def create_manual_payment(
    req: PaymentManualCreateRequest,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    payment = await PaymentService.create_manual_payment(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Payment recorded successfully",
        data={"payment": payment.model_dump(mode="json")},
    )


@router.put(
    "/payments/{payment_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Payment (Admin)",
    description="Updates an existing payment's fields (amount, status, method, date, remarks).",
)
async def update_payment(
    payment_id: str,
    req: PaymentUpdateRequest,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    payment = await PaymentService.update_payment(db, current_user, payment_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Payment updated successfully",
        data={"payment": payment.model_dump(mode="json")},
    )


# 2. Customer Payment Endpoints (read-only)
@router.get(
    "/customer/payments",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List My Payments (Customer)",
    description="Returns the authenticated customer's own payment history. Read-only.",
)
async def list_customer_payments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    payments = await PaymentService.get_customer_payments(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Payments retrieved successfully",
        data={"payments": [p.model_dump(mode="json") for p in payments]},
    )


@router.get(
    "/customer/payments/{payment_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get My Payment (Customer)",
    description="Returns a single payment belonging to the authenticated customer. Read-only.",
)
async def get_customer_payment(
    payment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    payment = await PaymentService.get_customer_payment_by_id(db, current_user, payment_id)
    return StandardSuccessResponse(
        success=True,
        message="Payment retrieved successfully",
        data={"payment": payment.model_dump(mode="json")},
    )
