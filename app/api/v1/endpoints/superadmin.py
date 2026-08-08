from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_superadmin
from app.schemas.auth import StandardSuccessResponse
from app.schemas.report import ReportPeriod
from app.schemas.superadmin import (
    TenantStatusUpdateRequest,
    TenantProvisionRequest,
    TenantAdminStatusUpdateRequest,
)
from app.schemas.export import ExportFormat
from app.services.superadmin_service import SuperAdminService

router = APIRouter(prefix="/superadmin")


# 1. Platform Dashboard / Statistics
@router.get(
    "/dashboard",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Platform Dashboard (SuperAdmin)",
    description="Platform-wide totals, tenant status breakdown, tenant growth trend, and recent tenants.",
)
async def get_platform_dashboard(
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    data = await SuperAdminService.get_platform_dashboard(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True,
        message="Platform dashboard retrieved successfully",
        data={"dashboard": data.model_dump(mode="json")},
    )


# 2. Tenant Management
@router.get(
    "/tenants",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Tenants (SuperAdmin)",
    description="Returns all platform tenants, newest first, with each tenant's primary Admin as a derived contact.",
)
async def list_tenants(
    status_filter: Optional[str] = Query(None, alias="status", description="Active | Inactive"),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    tenants = await SuperAdminService.get_tenants(db, current_user, status_filter)
    return StandardSuccessResponse(
        success=True,
        message="Tenants retrieved successfully",
        data={"tenants": [t.model_dump(mode="json") for t in tenants]},
    )


@router.get(
    "/tenants/{tenant_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Tenant Detail (SuperAdmin)",
    description="Returns a single tenant's detail, including its primary Admin as a derived contact.",
)
async def get_tenant_detail(
    tenant_id: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    tenant = await SuperAdminService.get_tenant_detail(db, current_user, tenant_id)
    return StandardSuccessResponse(
        success=True,
        message="Tenant retrieved successfully",
        data={"tenant": tenant.model_dump(mode="json")},
    )


@router.put(
    "/tenants/{tenant_id}/status",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Enable/Disable Tenant (SuperAdmin)",
    description="Sets a tenant's status to Active or Inactive. A pure status-flag toggle — does not cascade to blocking existing user logins.",
)
async def set_tenant_status(
    tenant_id: str,
    req: TenantStatusUpdateRequest,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    tenant = await SuperAdminService.set_tenant_status(db, current_user, tenant_id, req.status)
    return StandardSuccessResponse(
        success=True,
        message=f"Tenant {'enabled' if req.status == 'Active' else 'disabled'} successfully",
        data={"tenant": tenant.model_dump(mode="json")},
    )


@router.put(
    "/tenants/{tenant_id}/admin/status",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate/Deactivate Tenant's Admin Account (SuperAdmin)",
    description=(
        "Activates or deactivates the tenant's primary Admin account itself — unlike the tenant-level "
        "status toggle, this immediately blocks the Admin from logging in or using existing sessions."
    ),
)
async def set_tenant_admin_status(
    tenant_id: str,
    req: TenantAdminStatusUpdateRequest,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    admin = await SuperAdminService.set_tenant_admin_status(db, current_user, tenant_id, req.is_active)
    return StandardSuccessResponse(
        success=True,
        message=f"Admin account {'activated' if req.is_active else 'deactivated'} successfully",
        data={"admin": admin.model_dump(mode="json")},
    )


@router.post(
    "/tenants/{tenant_id}/admin/reset-password",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Force Password Reset for Tenant's Admin (SuperAdmin)",
    description=(
        "Issues a real password reset token for the tenant's primary Admin and emails a reset link, "
        "using the same token/email flow as the public forgot-password endpoint."
    ),
)
async def reset_tenant_admin_password(
    tenant_id: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    result = await SuperAdminService.reset_tenant_admin_password(db, current_user, tenant_id)
    return StandardSuccessResponse(
        success=True,
        message="Password reset link sent to the tenant's Admin",
        data={"reset": result.model_dump(mode="json")},
    )


@router.post(
    "/tenants/provision",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision New Tenant (SuperAdmin)",
    description=(
        "Real, production tenant provisioning — creates a Tenant, default Branch, Subscription, and Admin "
        "user in one transaction, generates a temporary password + activation link for the new Admin, sends "
        "an onboarding email, and audit-logs every step. Replaces the previous client-side-only mock dialog."
    ),
)
async def provision_tenant(
    req: TenantProvisionRequest,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    result = await SuperAdminService.provision_tenant(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message=f"'{result.tenant.name}' provisioned successfully",
        data={"provisioned": result.model_dump(mode="json")},
    )


@router.get(
    "/tenants/{tenant_id}/statistics",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Tenant Statistics (SuperAdmin)",
    description="Per-tenant business statistics, composed by reusing Module 12's ReportRepository against the target tenant.",
)
async def get_tenant_statistics(
    tenant_id: str,
    period: Optional[ReportPeriod] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    stats = await SuperAdminService.get_tenant_statistics(db, current_user, tenant_id, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True,
        message="Tenant statistics retrieved successfully",
        data={"statistics": stats.model_dump(mode="json")},
    )


# 3. Export (Module 15) — reusable export infrastructure, see
# app/services/export_service.py. Each endpoint reuses the exact same
# SuperAdminService method its sibling display endpoint above uses.

@router.get(
    "/export/dashboard",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Export Platform Dashboard (SuperAdmin)",
    description="Downloadable platform-wide KPI table as CSV, Excel, or Markdown. Feeds the SuperAdmin Dashboard's Export button.",
)
async def export_platform_dashboard(
    format: ExportFormat = Query("excel"),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    file = await SuperAdminService.export_platform_dashboard(db, current_user, format)
    return StandardSuccessResponse(
        success=True,
        message="Export generated successfully",
        data={"export": file.model_dump(mode="json")},
    )


@router.get(
    "/export/tenants",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Export Tenants (SuperAdmin)",
    description="Downloadable tenant list (optionally filtered by status) as CSV, Excel, or Markdown. Feeds the Tenant Management page's Export Excel button.",
)
async def export_tenants(
    format: ExportFormat = Query("excel"),
    status_filter: Optional[str] = Query(None, alias="status", description="Active | Inactive"),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    file = await SuperAdminService.export_tenants(db, current_user, status_filter, format)
    return StandardSuccessResponse(
        success=True,
        message="Export generated successfully",
        data={"export": file.model_dump(mode="json")},
    )
