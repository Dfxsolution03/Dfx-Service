from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user, require_admin_only
from app.schemas.auth import StandardSuccessResponse
from app.schemas.customer import (
    ProfileUpdateRequest,
    KYCSubmitRequest,
    KYCRejectRequest,
    AddressCreateRequest,
    AddressUpdateRequest,
)
from app.services.customer_service import CustomerService

router = APIRouter()


# 1. Profile Endpoints
@router.get(
    "/customer/profile",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Customer Profile",
    description="Returns detailed profile information for the authenticated customer.",
)
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    profile = await CustomerService.get_profile(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Customer profile retrieved successfully",
        data={"profile": profile.model_dump()},
    )


@router.put(
    "/customer/profile",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Customer Profile",
    description="Updates profile information for the authenticated customer.",
)
async def update_profile(
    req: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    updated_profile = await CustomerService.update_profile(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Customer profile updated successfully",
        data={"profile": updated_profile.model_dump()},
    )


# 2. KYC Endpoints
@router.get(
    "/customer/kyc",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get KYC Verification Status",
    description="Returns current identity KYC verification document status.",
)
async def get_kyc_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    kyc_data = await CustomerService.get_kyc(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="KYC status retrieved successfully",
        data={"kyc": kyc_data.model_dump() if kyc_data else None},
    )


@router.post(
    "/customer/kyc",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit KYC Verification Document",
    description="Submits identity document (PAN, Aadhaar, Passport) for store verification.",
)
async def submit_kyc_document(
    req: KYCSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    kyc_data = await CustomerService.submit_kyc(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="KYC document submitted successfully and is pending store verification",
        data={"kyc": kyc_data.model_dump()},
    )


# 2b. Admin KYC Review Endpoints
@router.get(
    "/kyc",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List KYC Submissions (Admin)",
    description="Returns all KYC submissions for the admin's tenant, newest first.",
)
async def list_kyc_records(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    records = await CustomerService.get_kyc_records_for_admin(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="KYC submissions retrieved successfully",
        data={"kyc_records": [r.model_dump() for r in records]},
    )


@router.get(
    "/kyc/{kyc_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get KYC Submission (Admin)",
    description="Returns a single KYC submission by ID, scoped to the admin's tenant.",
)
async def get_kyc_record(
    kyc_id: str,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    record = await CustomerService.get_kyc_record_for_admin(db, current_user, kyc_id)
    return StandardSuccessResponse(
        success=True,
        message="KYC submission retrieved successfully",
        data={"kyc_record": record.model_dump()},
    )


@router.put(
    "/kyc/{kyc_id}/approve",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve KYC Submission (Admin)",
    description="Approves a Pending KYC submission, marking the customer's identity as Verified.",
)
async def approve_kyc_record(
    kyc_id: str,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    record = await CustomerService.approve_kyc(db, current_user, kyc_id)
    return StandardSuccessResponse(
        success=True,
        message="KYC submission approved successfully",
        data={"kyc_record": record.model_dump()},
    )


@router.put(
    "/kyc/{kyc_id}/reject",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject KYC Submission (Admin)",
    description="Rejects a Pending KYC submission with a documented reason.",
)
async def reject_kyc_record(
    kyc_id: str,
    req: KYCRejectRequest,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    record = await CustomerService.reject_kyc(db, current_user, kyc_id, req)
    return StandardSuccessResponse(
        success=True,
        message="KYC submission rejected successfully",
        data={"kyc_record": record.model_dump()},
    )


# 3. Address Endpoints
@router.get(
    "/customer/addresses",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Customer Addresses",
    description="Returns list of saved shipping and billing addresses for the customer.",
)
async def list_addresses(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    addresses = await CustomerService.get_addresses(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Addresses retrieved successfully",
        data={"addresses": [a.model_dump() for a in addresses]},
    )


@router.post(
    "/customer/addresses",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add Customer Address",
    description="Adds a new shipping address to the customer's account.",
)
async def add_address(
    req: AddressCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    address = await CustomerService.add_address(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Address created successfully",
        data={"address": address.model_dump()},
    )


@router.put(
    "/customer/addresses/{address_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Customer Address",
    description="Updates an existing customer address.",
)
async def update_address(
    address_id: str,
    req: AddressUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    address = await CustomerService.update_address(db, current_user, address_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Address updated successfully",
        data={"address": address.model_dump()},
    )


@router.delete(
    "/customer/addresses/{address_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Customer Address",
    description="Deletes a customer address.",
)
async def delete_address(
    address_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await CustomerService.delete_address(db, current_user, address_id)
    return StandardSuccessResponse(
        success=True,
        message="Address deleted successfully",
        data={},
    )


@router.put(
    "/customer/addresses/{address_id}/default",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Set Default Address",
    description="Sets the specified address as the customer's primary default address.",
)
async def set_default_address(
    address_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    address = await CustomerService.set_default_address(db, current_user, address_id)
    return StandardSuccessResponse(
        success=True,
        message="Default address set successfully",
        data={"address": address.model_dump()},
    )


# 4. Branch Locator Endpoint (SCR-CUST-08)
@router.get(
    "/customer/branches",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Branch Locator",
    description="List active store branches for the customer's tenant (SCR-CUST-08).",
)
async def get_tenant_branches(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    branches = await CustomerService.get_branches(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Tenant store branches retrieved successfully",
        data={"branches": [b.model_dump() for b in branches]},
    )
