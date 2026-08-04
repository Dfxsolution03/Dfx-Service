from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user
from app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponseData,
    RefreshTokenRequest,
    LogoutRequest,
    UserResponse,
    TenantPublicItem,
    StandardSuccessResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    EmailVerificationConfirmRequest,
)
from app.services.auth_service import AuthService

router = APIRouter()


@router.get(
    "/tenants/public",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Active Jewellery Stores",
    description="Returns public list of active jewellery store tenants for customer registration selection.",
)
async def get_public_tenants(
    db: AsyncSession = Depends(get_async_db),
):
    tenants = await AuthService.get_public_tenants(db)
    items = [TenantPublicItem.model_validate(t) for t in tenants]
    return StandardSuccessResponse(
        success=True,
        message="Active store list fetched successfully",
        data={"tenants": items},
    )


@router.post(
    "/auth/signup",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Customer Registration",
    description="Registers a new customer account and associates them with their selected jewellery store.",
)
async def customer_signup(
    req: UserRegisterRequest,
    db: AsyncSession = Depends(get_async_db),
):
    user = await AuthService.register_customer(db, req)
    user_data = UserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        role=user.role.name,
        name=user.name,
        email=user.email,
        phone=user.phone,
        kyc_status=user.kyc_status,
        member_since=user.member_since,
        is_active=user.is_active,
    )
    return StandardSuccessResponse(
        success=True,
        message="Customer registered successfully. Please login to continue.",
        data={"user": user_data},
    )


@router.post(
    "/auth/login",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Unified User Login",
    description="Authenticates credentials (email or phone) and returns JWT Access & Refresh Tokens.",
)
async def user_login(
    req: UserLoginRequest,
    db: AsyncSession = Depends(get_async_db),
):
    token_data = await AuthService.login_user(db, req)
    return StandardSuccessResponse(
        success=True,
        message="Authentication successful",
        data=token_data.model_dump(),
    )


@router.post(
    "/auth/refresh",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh Token Rotation",
    description="Exchanges a valid refresh token for a new access token and rotated refresh token.",
)
async def refresh_tokens(
    req: RefreshTokenRequest,
    db: AsyncSession = Depends(get_async_db),
):
    token_data = await AuthService.refresh_token_flow(db, req.refresh_token)
    return StandardSuccessResponse(
        success=True,
        message="Tokens refreshed successfully",
        data=token_data.model_dump(),
    )


@router.post(
    "/auth/logout",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="User Logout",
    description="Revokes current refresh token or all active refresh tokens for the authenticated user.",
)
async def user_logout(
    req: LogoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await AuthService.logout_user(
        db,
        user_id=current_user.id,
        refresh_token_str=req.refresh_token,
        all_devices=req.all_devices,
    )
    return StandardSuccessResponse(
        success=True,
        message="Logged out successfully",
        data={},
    )


@router.post(
    "/auth/forgot-password",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Forgot Password",
    description="Sends a password reset link if the email matches an active account. Always returns the same generic response, whether or not a match was found, to prevent account enumeration.",
)
async def forgot_password(
    req: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_async_db),
):
    await AuthService.forgot_password(db, req)
    return StandardSuccessResponse(
        success=True,
        message="If an account exists for that email, a password reset link has been sent.",
        data={},
    )


@router.post(
    "/auth/reset-password",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset Password",
    description="Sets a new password using a valid, unexpired, unused reset token. Revokes all existing sessions on success.",
)
async def reset_password(
    req: ResetPasswordRequest,
    db: AsyncSession = Depends(get_async_db),
):
    await AuthService.reset_password(db, req)
    return StandardSuccessResponse(
        success=True,
        message="Password reset successfully. Please log in with your new password.",
        data={},
    )


@router.post(
    "/auth/email/verify/request",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Request Email Verification",
    description="Sends a verification link to the current user's own registered email address.",
)
async def request_email_verification(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await AuthService.request_email_verification(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Verification email sent.",
        data={},
    )


@router.post(
    "/auth/email/verify/confirm",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm Email Verification",
    description="Marks the account's email as verified using a valid, unexpired, unused verification token.",
)
async def confirm_email_verification(
    req: EmailVerificationConfirmRequest,
    db: AsyncSession = Depends(get_async_db),
):
    await AuthService.confirm_email_verification(db, req)
    return StandardSuccessResponse(
        success=True,
        message="Email address verified successfully.",
        data={},
    )


@router.get(
    "/users/me",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Current User Profile",
    description="Fetches profile information for the authenticated user.",
)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    user_data = UserResponse(
        id=current_user.id,
        tenant_id=current_user.tenant_id,
        role=current_user.role.name,
        name=current_user.name,
        email=current_user.email,
        phone=current_user.phone,
        kyc_status=current_user.kyc_status,
        member_since=current_user.member_since,
        is_active=current_user.is_active,
    )
    return StandardSuccessResponse(
        success=True,
        message="User profile retrieved successfully",
        data={"user": user_data},
    )
